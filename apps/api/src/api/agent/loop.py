"""One turn of the interview: the candidate says something, the interviewer answers.

The loop is deliberately hand-written rather than the SDK's tool runner. What happens
between tool calls here is not "call the function" — it is *persist a row*, so that a
crashed process leaves a session that can be read afterwards, and so that hints taken
during a turn are still counted at grading time. A helper that owns the loop owns those
decisions too.

Shape of one turn:

    candidate text  ->  persisted as a `turns` row
                    ->  model call (system = frozen prompt, messages = the whole transcript)
                    ->  while the model asks for tools: run them, persist, call again
                    ->  the final assistant text, persisted, and returned

The transcript is rebuilt from `turns` on every call rather than held in memory: the API is
stateless between requests, and the database is the only thing that survives a restart.

The call is streamed so the live channel has something to say while the model is thinking,
but `POST /turns` still answers with the finished message: deltas are a rendering
convenience and `agent.message.done` is authoritative (docs/API.md). A client that ignores
the stream sees exactly what it saw before.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, col, select

from api import events as event_bus
from api import llm
from api.agent import prompts, tools
from api.executor_client import CodeRunner
from api.mastery import apply_evidence, lock_projection
from api.models import ConceptEvidence, InterviewSession, Turn
from api.settings import Settings
from corpus.models import Item

logger = logging.getLogger(__name__)

# A turn that asks for tools, gets results, and asks again is normal. A turn that does it
# six times is a loop, and each iteration is a paid call against a budget the candidate is
# waiting on. The cap is a cost control, not a correctness one — it is reported, not hidden.
MAX_TOOL_ROUNDS = 5

# ...and a cap on tool *executions*, which is a different number. `MAX_TOOL_ROUNDS` bounds
# model calls; nothing bounded how many `tool_use` blocks one response could carry, and the
# loop executed every one of them. Measured with 60 blocks per response across the 5
# rounds: **300 executor round-trips inside one synchronous HTTP request**, 307 transcript
# rows, and 603 events against a 256-slot buffer — so one turn evicted the entire session's
# history (`item.presented`, `hint.revealed`, `grading.result`) with no `stream.gap`, since
# that check runs once, at stream open.
#
# A candidate reaches this without a malicious model, just by asking for it: "run each of
# these sixty variants". `check_answer` and `record_observation` already carry their own
# per-item rations; `run_code` — the only tool that reaches the executor — had none.
MAX_TOOL_CALLS_PER_TURN = 12

# `concept_evidence.source` for a row the interviewer wrote from the conversation, and the
# third producer of that table after session grading and the practice log. A distinct value
# because these rows are the softest evidence in the system and the first that could ever
# need excluding from a replay wholesale — which is only possible if they can be told apart.
OBSERVATION_SOURCE = "interviewer_observation"

# Bumped if what an observation means changes, exactly as a grader version is, so old rows
# stay interpretable.
OBSERVATION_VERSION = "interviewer.observation@1"


@dataclass(frozen=True)
class TurnResult:
    """What the route returns, and what a test asserts on."""

    text: str
    turns_written: int
    tool_calls: list[dict[str, Any]]
    hints_revealed: int
    ended: bool
    end_reason: str | None
    stop_reason: str | None
    truncated: bool


def transcript(db: Session, session_id: str) -> list[Turn]:
    """Every turn of this session, oldest first."""
    return list(
        db.exec(select(Turn).where(Turn.session_id == session_id).order_by(col(Turn.seq))).all()
    )


def next_seq(db: Session, session_id: str) -> int:
    rows = transcript(db, session_id)
    return (rows[-1].seq + 1) if rows else 1


def hints_revealed(db: Session, session_id: str, item_id: str) -> int:
    """How many hints this session has taken on this item.

    Counted from the turn record rather than a column. docs/GRADING.md called a column
    owed; the turns are already the authoritative account of what happened in a session,
    and a second place to record it is a second place to disagree.
    """
    levels = [
        int(row.tool_calls["level"])
        for row in transcript(db, session_id)
        if row.tool_calls
        and row.tool_calls.get("tool") == "reveal_hint"
        and row.tool_calls.get("item_id") == item_id
        and isinstance(row.tool_calls.get("level"), int)
    ]
    return max(levels, default=0)


def _tool_calls(db: Session, session_id: str, item_id: str, tool: str) -> list[dict[str, Any]]:
    """Every successful call of one tool against one item, in order.

    Rations are counted from the turn record rather than held in memory: `ToolContext` is
    rebuilt every turn, so a counter on it resets with each thing the candidate says — no cap
    at all against a model that simply asks again next turn. Errored calls do not count; a
    refused call did nothing, and charging for it would spend the ration on the model's own
    mistakes."""
    return [
        row.tool_calls
        for row in transcript(db, session_id)
        if row.tool_calls
        and row.tool_calls.get("tool") == tool
        and row.tool_calls.get("item_id") == item_id
        and not row.tool_calls.get("is_error")
    ]


def observations_recorded(db: Session, session_id: str, item_id: str) -> int:
    """How many observations this session has already recorded about this item."""
    return len(_tool_calls(db, session_id, item_id, "record_observation"))


def candidate_said(db: Session, session_id: str) -> str:
    """Everything the candidate has said this session, for checking a quoted span against.

    Their turns only. An observation citing the *interviewer's* words would be the model
    quoting its own leading question back as evidence, which is precisely the fabrication the
    citation check exists to catch."""
    return "\n".join(row.content for row in transcript(db, session_id) if row.role == "candidate")


def answer_checks(db: Session, session_id: str, item_id: str) -> int:
    """How many answers this session has already checked against this item.

    Counted from the turn record for the same reason hints are — see `_tool_calls`.
    """
    return len(_tool_calls(db, session_id, item_id, "check_answer"))


def as_messages(rows: list[Turn]) -> list[dict[str, Any]]:
    """The stored transcript as an alternating message list.

    Tool results are folded into the candidate's side as plain text rather than replayed as
    `tool_result` blocks. Replaying them faithfully would mean storing every `tool_use_id`
    and reconstructing the exact block structure; the model gets the same information this
    way, and a transcript that cannot be malformed is worth more here than one that is
    byte-faithful to a previous request.
    """
    messages: list[dict[str, Any]] = []
    for row in rows:
        role = "assistant" if row.role == "interviewer" else "user"
        content = row.content
        if row.role == "tool":
            content = (
                f"[tool result: {row.tool_calls.get('tool') if row.tool_calls else '?'}]\n{content}"
            )
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += f"\n\n{content}"
        else:
            messages.append({"role": role, "content": content})
    return messages


def delta_publisher(channel: event_bus.EventBus, session_id: str) -> Callable[[str], None]:
    """A callback that publishes one text chunk and returns nothing.

    Named rather than written inline because a lambda over `publish` returns the `Event` it
    created, and `on_delta` promises a sink whose result is ignored. The signature is the
    documentation of that, and mypy is right to insist on it.
    """

    def publish(chunk: str) -> None:
        channel.publish(session_id, "agent.message.delta", text=chunk)

    return publish


def _write(
    db: Session,
    session_id: str,
    seq: int,
    role: str,
    content: str,
    tool_calls: dict[str, Any] | None = None,
) -> Turn:
    row = Turn(session_id=session_id, seq=seq, role=role, content=content, tool_calls=tool_calls)
    db.add(row)
    db.commit()
    return row


def _write_observation(
    db: Session, session_row: InterviewSession, item: Item, observation: tools.Observation
) -> None:
    """One observation, as an immutable evidence row folded into the projection.

    Written here rather than in the tool because a tool that could reach a database is a
    tool that could write evidence without the loop knowing, and the loop owns the
    transcript the observation was cited against.

    The row is an ordinary `concept_evidence` row in every respect except its `source` and
    its confidence, which is the point: mastery is derived by replaying evidence, and a
    reading the projection had to be taught about specially would be a reading a replay
    could get wrong.
    """
    lock_projection(db)
    row = ConceptEvidence(
        concept_id=observation.concept_id,
        source=OBSERVATION_SOURCE,
        item_id=item.id,
        session_id=session_row.id,
        score=observation.score,
        confidence=observation.confidence,
        grader_version=OBSERVATION_VERSION,
    )
    db.add(row)
    db.flush()
    apply_evidence(db, row, user_id=session_row.user_id)
    db.commit()


def run_turn(
    db: Session,
    session_row: InterviewSession,
    item: Item,
    candidate_text: str,
    *,
    runner: CodeRunner | None = None,
    settings: Settings | None = None,
    client: Any = None,
    bus: event_bus.EventBus | None = None,
) -> TurnResult:
    """Take one candidate message and produce one interviewer reply.

    Every row is committed as it happens rather than at the end. A turn that dies halfway
    through — a provider timeout, a budget refusal on the second model call — leaves the
    candidate's message and any tool results already recorded, which is what makes the
    session readable afterwards instead of appearing never to have happened.
    """
    channel = bus or event_bus.bus()
    seq = next_seq(db, session_row.id)
    _write(db, session_row.id, seq, "candidate", candidate_text)
    seq += 1
    if seq == 2:
        # The first turn is where an item comes into play, and a client that joined the
        # stream before it started has no other way to learn which problem it is watching.
        channel.publish(
            session_row.id,
            "item.presented",
            item_id=item.id,
            title=item.title,
            statement_md=item.statement_md,
            expected_minutes=item.expected_minutes,
        )

    context = tools.ToolContext(
        item=item,
        runner=runner,
        hints_revealed=hints_revealed(db, session_row.id, item.id),
        answer_checks=answer_checks(db, session_row.id, item.id),
        observations_recorded=observations_recorded(db, session_row.id, item.id),
        # Built after the candidate's message for this turn is already written, so a span
        # quoting what they just said checks out.
        candidate_said=candidate_said(db, session_row.id),
    )
    system = prompts.system_prompt(session_row.mode, item)
    written = 1
    calls: list[dict[str, Any]] = []
    truncated = False

    for round_number in range(MAX_TOOL_ROUNDS):
        completion = llm.stream(
            job="interviewing",
            system=system,
            messages=as_messages(transcript(db, session_row.id)),
            tools=tools.TOOL_SCHEMAS,
            session_id=session_row.id,
            settings=settings,
            client=client,
            on_delta=delta_publisher(channel, session_row.id),
        )
        uses = [block for block in completion.content if getattr(block, "type", None) == "tool_use"]
        _write(
            db,
            session_row.id,
            seq,
            "interviewer",
            completion.text,
            {"uses": [{"tool": use.name, "input": use.input} for use in uses]} if uses else None,
        )
        seq += 1
        written += 1

        if not uses:
            # docs/API.md: `agent.message.done` is authoritative over any deltas. It is
            # published for a text-only turn and after the last tool round alike, so a
            # client always has exactly one authoritative message per turn.
            channel.publish(
                session_row.id,
                "agent.message.done",
                message_id=str(seq - 1),
                text=completion.text,
            )
            return TurnResult(
                text=completion.text,
                turns_written=written,
                tool_calls=calls,
                hints_revealed=context.hints_revealed,
                ended=context.ended,
                end_reason=context.end_reason,
                stop_reason=completion.stop_reason,
                truncated=False,
            )

        for use in uses:
            if len(calls) >= MAX_TOOL_CALLS_PER_TURN:
                truncated = True
                break
            arguments = use.input if isinstance(use.input, dict) else {}
            channel.publish(
                session_row.id,
                "agent.tool_use",
                tool=use.name,
                input=arguments,
                tool_use_id=getattr(use, "id", None),
            )
            outcome = tools.dispatch(use.name, arguments, context)
            channel.publish(
                session_row.id,
                "tool.result",
                tool=use.name,
                tool_use_id=getattr(use, "id", None),
                output=outcome.output,
                is_error=outcome.is_error,
            )
            if use.name == "reveal_hint" and not outcome.is_error:
                # Carried explicitly, with its price: you should see what a hint cost at
                # the moment you take it, not discover it in the report (docs/API.md).
                channel.publish(
                    session_row.id,
                    "hint.revealed",
                    item_id=item.id,
                    level=outcome.output["level"],
                    text=outcome.output["text"],
                    score_penalty=outcome.output["score_penalty"],
                )
            if use.name == "record_observation" and not outcome.is_error:
                observation = context.observations[-1]
                _write_observation(db, session_row, item, observation)
                channel.publish(
                    session_row.id,
                    "observation.recorded",
                    concept_id=observation.concept_id,
                    signal=observation.signal,
                )
            record: dict[str, Any] = {
                "tool": use.name,
                "item_id": item.id,
                "is_error": outcome.is_error,
            }
            if use.name == "reveal_hint" and not outcome.is_error:
                record["level"] = outcome.output["level"]
            if use.name == "record_observation" and not outcome.is_error:
                record["concept_id"] = context.observations[-1].concept_id
                record["signal"] = context.observations[-1].signal
            _write(db, session_row.id, seq, "tool", outcome.as_text(), record)
            seq += 1
            written += 1
            calls.append({"tool": use.name, "input": arguments, "is_error": outcome.is_error})

        if truncated:
            logger.warning(
                "session %s hit the %s-call tool cap in one turn",
                session_row.id,
                MAX_TOOL_CALLS_PER_TURN,
            )
            break
        if round_number == MAX_TOOL_ROUNDS - 1:
            truncated = True
            logger.warning(
                "session %s hit the %s-round tool cap in one turn",
                session_row.id,
                MAX_TOOL_ROUNDS,
            )

    # The cap was reached with the model still asking for tools. Say so in the transcript
    # rather than returning an empty reply the candidate cannot interpret.
    message = "I need a moment — let me stop there and come back to it. What have you got so far?"
    _write(db, session_row.id, seq, "interviewer", message, {"truncated": True})
    channel.publish(session_row.id, "agent.message.done", message_id=str(seq), text=message)
    return TurnResult(
        text=message,
        turns_written=written + 1,
        tool_calls=calls,
        hints_revealed=context.hints_revealed,
        ended=context.ended,
        end_reason=context.end_reason,
        stop_reason="tool_round_cap",
        truncated=truncated,
    )


def tool_json(outcome_text: str) -> dict[str, Any]:
    """Parse a stored tool result back. Only used by tests and the report; a malformed one
    is a bug worth seeing rather than swallowing."""
    parsed = json.loads(outcome_text)
    return parsed if isinstance(parsed, dict) else {"value": parsed}
