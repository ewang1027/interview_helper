"""The interviewer's entire capability surface, and what each tool actually does.

docs/API.md lists five tools and all five are implemented here. The surface is deliberately
small — docs/SECURITY.md's answer to prompt injection is not filtering, it is that
succeeding buys the attacker almost nothing. There is no tool that writes the corpus, sends
anything outbound or reads a secret, and grading is not a tool at all, so the interviewer
cannot score itself.

Two tools deviate from the signature docs/API.md specifies, both in the same direction —
taking away a parameter that let the model choose what it was measured against:

**`run_code` does not take tests.** docs/API.md's signature has the caller passing
`tests[]`; here the tests come from the corpus item and the model supplies only the source.
Letting the model choose the tests would let it run a payload of its own devising *and*
mark its own work, which are the two things this design spends the most effort preventing.

**`check_answer` does not take an `item_id`** (2026-08-21). docs/API.md specifies
`{ item_id, submitted }`, and argues two paragraphs later that `reveal_hint` takes no item
id because naming a different one would be a way to read ahead. That argument applies here
unchanged and the signature had not caught up: there is exactly one item in play, so the
tool reads it from the context.

**`check_answer` is also the only tool that is an oracle**, and it is capped for it. Ask it
about 1, then 2, then 3, and you have the answer without the candidate having thought about
anything — which is precisely what a model trying to be helpful does, the same failure mode
`reveal_hint`'s monotonic check exists for. `MAX_ANSWER_CHECKS` successful checks per item
per session is enough for a candidate revising a stated answer and nowhere near enough to
search. The count is recovered from the turn record, not held in memory, because a context
is rebuilt every turn and an in-memory counter would cap nothing.

**`record_observation` does not write anything.** It is the tool that produces evidence, and
tools here cannot reach a database — that is the property that makes the interviewer unable
to score itself. So it validates the observation and hands it back on the context, and the
turn loop, which does hold a session, writes the row. See `api.agent.loop`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from api.executor_client import CodeRunner, ExecutorProtocolError, ExecutorUnavailableError
from api.grading.coding import hint_penalty
from api.grading.quant import check_answer
from api.grading.rubric import cites_the_answer
from corpus.loader import load_concepts
from corpus.models import Item

logger = logging.getLogger(__name__)

# How many times the interviewer may check an answer against one item. An oracle with no
# limit is a way to read the answer off the grader; a candidate revising theirs needs two
# or three. Chosen, not calibrated — the number is here to be raised if real sessions say so.
MAX_ANSWER_CHECKS = 3

# How many observations the interviewer may record about one item. Each one moves mastery,
# and unlike a grading they are not independent of each other — three readings of one
# conversation are still one conversation. At the ceiling below, three of them carry about
# 0.75 of a single coding grading's confidence, which is the intended order: what was said
# matters, and it matters less than what was submitted.
MAX_OBSERVATIONS = 3

# The ceiling on an observation's confidence, and the lowest number in the system. A rubric
# judgement is a model's read of prose against anchors, with its citation checked, and it
# gets 0.5. An observation is a model's read of a conversation, mid-flight, with no anchors
# at all. The model supplies its own confidence and it is scaled by this rather than
# trusted — a model asked how sure it is answers "very".
OBSERVATION_CONFIDENCE = 0.25

# What an observation can claim, and what it is worth as a score. There is deliberately no
# "never mentioned it" signal: silence is not evidence (docs/GRADING.md), and the span
# requirement enforces that structurally — there is nothing to quote.
OBSERVATION_SIGNALS: dict[str, float] = {"strong": 1.0, "shaky": 0.5, "wrong": 0.0}


@lru_cache
def _concept_ids() -> frozenset[str]:
    """The taxonomy, for refusing an observation about a concept that does not exist.

    `concept_evidence.concept_id` is a foreign key, so an unresolvable one is an insert
    failure in the middle of a turn rather than something the model can be told about."""
    return frozenset(concept.id for concept in load_concepts())


# Ordered, and the order is load-bearing: `tools` renders above `system` in the cached
# prefix, so a set iterated in hash order would invalidate the cache between processes.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "run_code",
        "description": (
            "Run the candidate's code against this problem's own hidden tests and return "
            "what passed. Use this to check a claim about code rather than reading it. "
            "The tests belong to the problem; you cannot choose or add to them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "language": {"type": "string", "enum": ["python"]},
                "source": {"type": "string", "description": "The complete program to run."},
            },
            "required": ["language", "source"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reveal_hint",
        "description": (
            "Give the candidate the next hint. Hints are graduated, least to most "
            "revealing, and each one costs the candidate part of their score — the cost "
            "is returned so you can tell them what it cost. Levels are 1-indexed and "
            "must be taken in order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "minimum": 1, "description": "1-indexed hint."}
            },
            "required": ["level"],
            "additionalProperties": False,
        },
    },
    {
        "name": "check_answer",
        "description": (
            "Check the answer the candidate has stated against this problem's own answer. "
            "Pass their answer exactly as they gave it. Use this to find out whether they "
            "are right before deciding what to ask next — not to explore what the answer "
            f"might be: you may check at most {MAX_ANSWER_CHECKS} times on this problem, "
            "and a check is not a hint."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "submitted": {
                    "type": "string",
                    "description": "The candidate's stated answer, in their own words.",
                }
            },
            "required": ["submitted"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_observation",
        "description": (
            "Record something the candidate's own words showed about one concept, so it "
            "counts towards what gets drilled next. Quote them verbatim in `span` — it is "
            "checked against what they actually said, and an observation you cannot point "
            "at is not recorded. Only what they demonstrated: there is no way to record "
            "that someone failed to mention something, because not saying a thing is not "
            f"evidence about it. At most {MAX_OBSERVATIONS} per problem."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "concept_id": {
                    "type": "string",
                    "description": "A concept id from this project's taxonomy.",
                },
                "signal": {
                    "type": "string",
                    "enum": sorted(OBSERVATION_SIGNALS),
                    "description": (
                        "strong: they showed it. shaky: partial or hesitant. "
                        "wrong: they said something incorrect about it."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "How sure you are, relative to your other observations.",
                },
                "span": {
                    "type": "string",
                    "description": "The candidate's own words, quoted exactly.",
                },
            },
            "required": ["concept_id", "signal", "confidence", "span"],
            "additionalProperties": False,
        },
    },
    {
        "name": "end_round",
        "description": (
            "Finish with this problem — solved, abandoned, or out of time. Say why in one "
            "line. The application decides what happens next; you do not move on yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = frozenset(schema["name"] for schema in TOOL_SCHEMAS)


@dataclass(frozen=True)
class Observation:
    """One thing the conversation showed, validated and waiting to be written.

    Carries the score and confidence already resolved, so the loop writes a row rather than
    re-deciding what the model's words were worth."""

    concept_id: str
    signal: str
    score: float
    confidence: float
    span: str


@dataclass
class ToolContext:
    """What the tools are allowed to act on: one item, one runner, and the hints already
    taken. Not a session and not a database handle — a tool that cannot reach the database
    cannot write evidence, which is the point."""

    item: Item
    runner: CodeRunner | None = None
    hints_revealed: int = 0
    answer_checks: int = 0
    observations_recorded: int = 0
    # Everything the candidate has said this session, for checking a quoted span against.
    # Their words only: an observation citing the interviewer's own turn would be the model
    # quoting itself, which is the fabrication the citation check exists to catch.
    candidate_said: str = ""
    ended: bool = False
    end_reason: str | None = None
    hints_taken: list[int] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)


@dataclass(frozen=True)
class ToolOutcome:
    """A tool's result as the model will see it, plus whether it was an error.

    `is_error` is not decoration: a tool result the model cannot tell failed produces a
    confident interviewer acting on nothing."""

    output: dict[str, Any]
    is_error: bool = False

    def as_text(self) -> str:
        return json.dumps(self.output, sort_keys=True)


def dispatch(name: str, arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """Run one tool call. Never raises: a tool that throws would abort a turn the candidate
    is in the middle of, and an error the model can read is recoverable."""
    try:
        if name == "run_code":
            return _run_code(arguments, context)
        if name == "reveal_hint":
            return _reveal_hint(arguments, context)
        if name == "check_answer":
            return _check_answer(arguments, context)
        if name == "record_observation":
            return _record_observation(arguments, context)
        if name == "end_round":
            return _end_round(arguments, context)
    except Exception as exc:  # pragma: no cover - the guard, not a path
        logger.exception("tool %s failed", name)
        return ToolOutcome({"error": f"{type(exc).__name__}: {exc}"}, is_error=True)
    return ToolOutcome({"error": f"No such tool: {name!r}."}, is_error=True)


def _run_code(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    grading = context.item.grading or {}
    if grading.get("type") != "tests":
        return ToolOutcome({"error": f"{context.item.id} has no runnable tests."}, is_error=True)
    if context.runner is None:  # pragma: no cover - wiring error, not a model error
        return ToolOutcome({"error": "No executor is available."}, is_error=True)

    language = arguments.get("language", "python")
    if language not in (grading.get("languages") or []):
        return ToolOutcome(
            {"error": f"{language!r} is not one of this problem's languages."}, is_error=True
        )
    limits = grading.get("limits") or {}
    try:
        result = context.runner.run_tests(
            language=language,
            source=str(arguments.get("source", "")),
            entrypoint=grading["entrypoint"],
            tests=grading["tests"],
            wall_ms=limits.get("wall_ms"),
            memory_mb=limits.get("memory_mb"),
        )
    except ExecutorUnavailableError as exc:
        return ToolOutcome({"error": f"The code runner is unavailable: {exc}"}, is_error=True)
    except ExecutorProtocolError as exc:
        return ToolOutcome({"error": f"The code runner refused this: {exc}"}, is_error=True)

    # Passes are a count; only failures are enumerated (docs/API.md). Handing the model
    # every passing case would spend context on the part that carries no information.
    return ToolOutcome(
        {
            "outcome": result.outcome,
            "passed": result.passed,
            "total": result.total,
            "failures": [failure.model_dump() for failure in result.failures[:3]],
            "detail": result.detail,
            "gradeable": result.is_gradeable,
        }
    )


def _reveal_hint(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    hints = context.item.hints
    if not hints:
        return ToolOutcome({"error": "This problem has no hints."}, is_error=True)
    try:
        level = int(arguments.get("level", 0))
    except (TypeError, ValueError):
        return ToolOutcome({"error": "level must be an integer."}, is_error=True)
    if not 1 <= level <= len(hints):
        return ToolOutcome(
            {"error": f"Hint levels for this problem are 1 to {len(hints)}."}, is_error=True
        )
    if level > context.hints_revealed + 1:
        # Monotonic by contract (docs/API.md): level N implies N-1 was given. Enforced
        # rather than trusted, because skipping to the last hint is exactly what a model
        # trying to be helpful does, and it is the most expensive one.
        return ToolOutcome(
            {"error": f"Hints are taken in order; the next one is {context.hints_revealed + 1}."},
            is_error=True,
        )
    context.hints_revealed = max(context.hints_revealed, level)
    context.hints_taken.append(level)
    return ToolOutcome(
        {
            "level": level,
            "text": hints[level - 1],
            "score_penalty": round(hint_penalty(level), 4),
            "hints_remaining": len(hints) - level,
        }
    )


def _check_answer(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """The same check grading runs, offered mid-interview and rationed.

    A thin proxy onto `api.grading.quant.check_answer` on purpose: an interviewer told "that
    is right" during the round and a grader that then scores it zero would be two different
    answers to one question, and the candidate would have no way to tell which was real.
    """
    grading = context.item.grading or {}
    if grading.get("type") != "answer":
        return ToolOutcome(
            {"error": f"{context.item.id} is not graded by an answer."}, is_error=True
        )
    submitted = str(arguments.get("submitted", "")).strip()
    if not submitted:
        return ToolOutcome(
            {"error": "submitted must be the answer the candidate stated."}, is_error=True
        )
    if context.answer_checks >= MAX_ANSWER_CHECKS:
        # The refusal says what to do instead, because a model that is only told "no" tends
        # to rephrase and try again.
        return ToolOutcome(
            {
                "error": (
                    f"You have already checked {context.answer_checks} answers on this "
                    "problem, which is the limit. Ask the candidate to commit to an answer "
                    "and reason about it with them instead."
                )
            },
            is_error=True,
        )

    context.answer_checks += 1
    checked = check_answer(context.item, submitted)
    return ToolOutcome(
        {
            "correct": checked.correct,
            "normalized": checked.submitted,
            "method": checked.method,
            "checks_remaining": MAX_ANSWER_CHECKS - context.answer_checks,
        }
    )


def _record_observation(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    """Validate one observation. Writing it is the loop's job — see this module's docstring.

    Three things have to hold before a conversation is allowed to move mastery, and each is
    a rule this project already applies somewhere else:

    - **The concept exists.** `concept_evidence.concept_id` is a foreign key.
    - **The span is really the candidate's.** Checked with the rubric grader's own citation
      check, against what the candidate said and not what the interviewer said. A model
      quoting its own leading question as evidence is exactly the fabrication that check was
      written for.
    - **There is a ration.** Three readings of one conversation are still one conversation.
    """
    if context.observations_recorded >= MAX_OBSERVATIONS:
        return ToolOutcome(
            {
                "error": (
                    f"You have recorded {context.observations_recorded} observations on this "
                    "problem, which is the limit. Keep interviewing; what they submit is "
                    "graded separately."
                )
            },
            is_error=True,
        )

    concept_id = str(arguments.get("concept_id", "")).strip()
    if concept_id not in _concept_ids():
        return ToolOutcome(
            {"error": f"{concept_id!r} is not a concept in this project's taxonomy."},
            is_error=True,
        )

    signal = str(arguments.get("signal", "")).strip()
    if signal not in OBSERVATION_SIGNALS:
        return ToolOutcome(
            {"error": f"signal must be one of {sorted(OBSERVATION_SIGNALS)}."}, is_error=True
        )

    span = str(arguments.get("span", ""))
    if not cites_the_answer(span, context.candidate_said):
        # Same demotion the rubric grader applies, one step earlier: there, an uncited
        # criterion is scored zero; here there is nothing to score, so it is simply refused.
        return ToolOutcome(
            {
                "error": (
                    "That span is not in what the candidate said. Quote them verbatim, at "
                    "least a dozen characters, and do not quote yourself."
                )
            },
            is_error=True,
        )

    try:
        stated = float(arguments.get("confidence", 0.0))
    except (TypeError, ValueError):
        return ToolOutcome({"error": "confidence must be a number in [0, 1]."}, is_error=True)

    observation = Observation(
        concept_id=concept_id,
        signal=signal,
        score=OBSERVATION_SIGNALS[signal],
        # Scaled, not trusted. A model asked how sure it is answers "very", and this is the
        # ceiling the application owns rather than one the model can talk its way past.
        confidence=round(max(0.0, min(1.0, stated)) * OBSERVATION_CONFIDENCE, 4),
        span=span,
    )
    context.observations.append(observation)
    context.observations_recorded += 1
    return ToolOutcome(
        {
            "ok": True,
            "concept_id": concept_id,
            "signal": signal,
            "observations_remaining": MAX_OBSERVATIONS - context.observations_recorded,
        }
    )


def _end_round(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    context.ended = True
    context.end_reason = str(arguments.get("reason", "")).strip() or "no reason given"
    return ToolOutcome({"ok": True, "reason": context.end_reason})
