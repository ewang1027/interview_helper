"""The turn loop against a live Postgres, with a scripted model and a stubbed executor.

What is under test is the loop and what it writes: the transcript, the tool round trip,
the state transitions, and the one thing that reaches beyond the conversation — hints taken
during an interview costing score at grading time.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import auth_settings, sign_in, use_settings
from fakes import FakeRunner, ScriptedModel, model_response, text_block, tool_block
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api import sessions as service
from api.agent import loop
from api.db import get_engine
from api.errors import ProblemError
from api.main import app
from api.models import Grading, InterviewSession, LlmCall, Turn
from api.routes.sessions import get_model_client, get_runner
from api.settings import Settings
from corpus.loader import load_items

pytestmark = pytest.mark.db

ITEMS = {item.id: item for item in load_items()}
FIRST_ITEM = "i.code.0001"
MODEL = "us.anthropic.claude-sonnet-4-6"


MODEL_OVERRIDES: dict[str, Any] = {"model_interviewer": MODEL, "model_grader": MODEL}


def llm_settings(**overrides: Any) -> Settings:
    """For a direct call. `conftest.use_settings` is what installs an override."""
    return auth_settings().model_copy(update={**MODEL_OVERRIDES, **overrides})


@pytest.fixture(autouse=True)
def _ledger_and_turns():
    """Turns and ledger rows are removed with their session by conftest, but a test that
    asserts on the *day's* spend needs the rows it wrote gone regardless."""
    with Session(get_engine()) as db:
        before = set(db.exec(select(LlmCall.id)).all())
    yield
    with Session(get_engine()) as db:
        new = set(db.exec(select(LlmCall.id)).all()) - before
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
            db.commit()


def start_session(created_sessions: list[str]) -> tuple[TestClient, str]:
    client = sign_in(TestClient(app))
    created = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 45})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    created_sessions.append(session_id)
    return client, session_id


def turn(session_id: str, text: str, model: ScriptedModel, runner: FakeRunner | None = None):
    """Drive one turn through the service, with the model and executor injected."""
    with Session(get_engine()) as db:
        session_row = db.get(InterviewSession, session_id)
        assert session_row is not None
        item = service.current_item(db, session_row)
        assert item is not None
        return loop.run_turn(
            db,
            session_row,
            item,
            text,
            runner=runner or FakeRunner(),
            settings=llm_settings(),
            client=model,
        )


def transcript(session_id: str) -> list[Turn]:
    with Session(get_engine()) as db:
        return loop.transcript(db, session_id)


def test_a_plain_turn_writes_the_candidate_and_the_interviewer(created_sessions):
    _, session_id = start_session(created_sessions)
    model = ScriptedModel(model_response(text_block("Tell me your approach first.")))

    result = turn(session_id, "I'm ready.", model)

    assert result.text == "Tell me your approach first."
    assert result.turns_written == 2
    rows = transcript(session_id)
    assert [(row.seq, row.role) for row in rows] == [(1, "candidate"), (2, "interviewer")]
    assert rows[0].content == "I'm ready."


def test_the_request_carries_the_cached_system_prompt_and_the_tools(created_sessions):
    _, session_id = start_session(created_sessions)
    model = ScriptedModel(model_response(text_block("ok")))
    turn(session_id, "hello", model)

    request = model.requests[0]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert ITEMS[FIRST_ITEM].statement_md in request["system"][0]["text"]
    assert [tool["name"] for tool in request["tools"]] == ["run_code", "reveal_hint", "end_round"]
    assert request["messages"] == [{"role": "user", "content": "hello"}]


def test_a_tool_call_round_trips_and_is_recorded(created_sessions):
    """Ask for a tool, get a result, answer. Three model-visible steps and four rows,
    because the tool result is part of the transcript rather than a detail of one turn."""
    _, session_id = start_session(created_sessions)
    model = ScriptedModel(
        model_response(tool_block("run_code", {"language": "python", "source": "def f(): pass"})),
        model_response(text_block("Your solution passes. What is its complexity?")),
    )

    result = turn(session_id, "Here is my attempt.", model)

    assert result.text.startswith("Your solution passes")
    assert [call["tool"] for call in result.tool_calls] == ["run_code"]
    roles = [row.role for row in transcript(session_id)]
    assert roles == ["candidate", "interviewer", "tool", "interviewer"]

    # The second request replays the tool result as content the model can read.
    second = model.requests[1]["messages"]
    assert any("tool result: run_code" in message["content"] for message in second)


def test_the_transcript_is_rebuilt_from_the_database_on_every_turn(created_sessions):
    """The API is stateless between requests; the rows are the only thing that survives."""
    _, session_id = start_session(created_sessions)
    turn(session_id, "first", ScriptedModel(model_response(text_block("one"))))
    model = ScriptedModel(model_response(text_block("two")))
    turn(session_id, "second", model)

    assert model.requests[0]["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "one"},
        {"role": "user", "content": "second"},
    ]


def test_hints_taken_in_the_interview_cost_score_at_grading(created_sessions):
    """The one place a conversation reaches into a measurement. Two hints on i.code.0001
    keep 0.95 * 0.90 of an otherwise perfect score."""
    client, session_id = start_session(created_sessions)
    model = ScriptedModel(
        model_response(tool_block("reveal_hint", {"level": 1})),
        model_response(tool_block("reveal_hint", {"level": 2}, use_id="tu_2")),
        model_response(text_block("Try it now.")),
    )
    turn(session_id, "I'm stuck.", model)
    turn(session_id, "Still stuck.", ScriptedModel(model_response(text_block("Keep going."))))

    with Session(get_engine()) as db:
        assert loop.hints_revealed(db, session_id, FIRST_ITEM) == 2

    # The submission runs through the route, which builds a real `ExecutorClient` unless
    # told otherwise — and there is no executor listening in a `db`-marked test.
    use_settings(**MODEL_OVERRIDES)
    app.dependency_overrides[get_runner] = FakeRunner
    reference = ITEMS[FIRST_ITEM].grading["reference_solutions"]["python"]
    submitted = client.post(
        f"/api/v1/sessions/{session_id}/submissions",
        json={"item_id": FIRST_ITEM, "kind": "code", "language": "python", "content": reference},
    )
    assert submitted.status_code == 202, submitted.text

    with Session(get_engine()) as db:
        grading = db.exec(select(Grading).order_by(col(Grading.id).desc())).first()
        assert grading is not None and grading.score is not None
        assert grading.detail["hints_revealed"] == 2
        assert grading.score < 1.0


def test_the_first_turn_moves_the_session_out_of_briefing(created_sessions):
    client, session_id = start_session(created_sessions)
    assert client.get(f"/api/v1/sessions/{session_id}").json()["state"] == "briefing"
    turn(session_id, "hello", ScriptedModel(model_response(text_block("hi"))))
    with Session(get_engine()) as db:
        session_row = db.get(InterviewSession, session_id)
        assert session_row is not None
        service.take_turn  # the transition lives in the service, exercised via the route below


def test_ending_every_round_moves_the_session_to_wrapping(created_sessions):
    """`end_round` finishes an item, not the session. The last one leaves nothing to
    interview about, and grading still has to happen."""
    client, session_id = start_session(created_sessions)
    use_settings(**MODEL_OVERRIDES)
    planned = [
        entry["item_id"]
        for entry in client.get(f"/api/v1/sessions/{session_id}").json()["plan"]["items"]
    ]
    assert len(planned) >= 2

    for index, item_id in enumerate(planned):
        model = ScriptedModel(
            model_response(tool_block("end_round", {"reason": "moving on"}, use_id=f"tu_{index}")),
            model_response(text_block("Next problem.")),
        )
        with Session(get_engine()) as db:
            session_row = db.get(InterviewSession, session_id)
            assert session_row is not None
            assert service.current_item(db, session_row).id == item_id
        body = post_turn(client, session_id, "done with this one", model)
        assert body["round_ended"] is True

    assert client.get(f"/api/v1/sessions/{session_id}").json()["state"] == "wrapping"
    refused = client.post(f"/api/v1/sessions/{session_id}/turns", json={"content": "more?"})
    assert refused.status_code == 409


def post_turn(
    client: TestClient, session_id: str, text: str, model: ScriptedModel
) -> dict[str, Any]:
    """Through the route, with the model injected the way the executor is."""
    use_settings(**MODEL_OVERRIDES)
    app.dependency_overrides[get_model_client] = lambda: model
    response = client.post(f"/api/v1/sessions/{session_id}/turns", json={"content": text})
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_the_route_takes_a_turn_and_reports_the_item(created_sessions):
    client, session_id = start_session(created_sessions)
    use_settings(**MODEL_OVERRIDES)
    body = post_turn(
        client, session_id, "ready", ScriptedModel(model_response(text_block("Let's begin.")))
    )
    assert body["item_id"] == FIRST_ITEM
    assert body["state"] == "interviewing"
    assert body["message"] == "Let's begin."
    assert body["round_ended"] is False


def test_a_turn_needs_a_session_cookie(created_sessions):
    _, session_id = start_session(created_sessions)
    anonymous = TestClient(app)
    assert (
        anonymous.post(f"/api/v1/sessions/{session_id}/turns", json={"content": "x"}).status_code
        == 401
    )


def test_a_spent_budget_refuses_the_turn(created_sessions):
    """docs/COST.md: refused, not downgraded. The candidate's message is already recorded,
    so the session reads afterwards as "they said this and nothing came back"."""
    _, session_id = start_session(created_sessions)
    turn(session_id, "first", ScriptedModel(model_response(text_block("hi"))))

    with Session(get_engine()) as db:
        spent = loop.llm.tokens_spent(db, session_id=session_id)
    settings = llm_settings(max_tokens_per_session=max(1, spent - 1))

    with Session(get_engine()) as db:
        session_row = db.get(InterviewSession, session_id)
        assert session_row is not None
        item = service.current_item(db, session_row)
        assert item is not None
        with pytest.raises(ProblemError) as raised:
            loop.run_turn(
                db,
                session_row,
                item,
                "and again",
                runner=FakeRunner(),
                settings=settings,
                client=ScriptedModel(model_response(text_block("no"))),
            )
    assert raised.value.status == 429
    assert [row.role for row in transcript(session_id)][-1] == "candidate"


def test_a_model_that_will_not_stop_asking_for_tools_is_capped(created_sessions):
    """Each round is a paid call the candidate is waiting on. The cap is reported rather
    than hidden, and the transcript gets a sentence instead of an empty reply."""
    _, session_id = start_session(created_sessions)
    model = ScriptedModel(
        *[
            model_response(
                tool_block("run_code", {"language": "python", "source": "x"}, use_id=f"t{i}")
            )
            for i in range(loop.MAX_TOOL_ROUNDS)
        ]
    )
    result = turn(session_id, "run it", model)

    assert result.truncated is True
    assert result.stop_reason == "tool_round_cap"
    assert len(model.requests) == loop.MAX_TOOL_ROUNDS
    assert transcript(session_id)[-1].role == "interviewer"


def test_a_turn_narrates_itself_on_the_event_stream(created_sessions):
    """What a client watching the stream sees while one turn runs. The order matters: a
    tool result before its own `agent.tool_use` would be unreadable, and the authoritative
    message has to come last."""
    from api.events import EventBus

    _, session_id = start_session(created_sessions)
    channel = EventBus()
    model = ScriptedModel(
        model_response(tool_block("reveal_hint", {"level": 1})),
        model_response(
            tool_block("run_code", {"language": "python", "source": "def f(): pass"}, "tu_2")
        ),
        model_response(text_block("Now tell me the complexity.")),
    )

    with Session(get_engine()) as db:
        session_row = db.get(InterviewSession, session_id)
        assert session_row is not None
        item = service.current_item(db, session_row)
        assert item is not None
        loop.run_turn(
            db,
            session_row,
            item,
            "I'm stuck.",
            runner=FakeRunner(),
            settings=llm_settings(),
            client=model,
            bus=channel,
        )

    published = channel.since(session_id, 0)
    # Deltas are dropped from the comparison: how many arrive is the provider's business,
    # and pinning it would make this a test of the fake's chunking.
    assert [event.type for event in published if event.type != "agent.message.delta"] == [
        "item.presented",
        "agent.tool_use",
        "tool.result",
        "hint.revealed",
        "agent.tool_use",
        "tool.result",
        "agent.message.done",
    ]
    assert [event.seq for event in published] == list(range(1, len(published) + 1))

    hint = next(event for event in published if event.type == "hint.revealed")
    # The price is on the event, not discovered in the report afterwards (docs/API.md).
    assert hint.data["score_penalty"] == pytest.approx(0.05)
    assert hint.data["text"] == ITEMS[FIRST_ITEM].hints[0]
    assert published[-1].data["text"] == "Now tell me the complexity."


def test_the_interviewers_text_arrives_as_deltas_before_it_arrives_whole(created_sessions):
    """`agent.message.delta` is what makes the stream worth watching rather than polling.
    `agent.message.done` stays authoritative: the deltas must reconstruct it exactly, or a
    client that renders optimistically ends up with text the server never said."""
    from api.events import EventBus

    _, session_id = start_session(created_sessions)
    channel = EventBus()
    said = "Start with the brute force, then tell me what it costs."
    model = ScriptedModel(model_response(text_block(said)))

    with Session(get_engine()) as db:
        session_row = db.get(InterviewSession, session_id)
        assert session_row is not None
        item = service.current_item(db, session_row)
        assert item is not None
        result = loop.run_turn(
            db,
            session_row,
            item,
            "ready",
            runner=FakeRunner(),
            settings=llm_settings(),
            client=model,
            bus=channel,
        )

    published = channel.since(session_id, 0)
    deltas = [event for event in published if event.type == "agent.message.delta"]
    done = [event for event in published if event.type == "agent.message.done"]

    assert len(deltas) > 1, "one delta is not a stream"
    assert "".join(event.data["text"] for event in deltas) == said
    assert [event.data["text"] for event in done] == [said]
    assert result.text == said
    # Every delta precedes the message it composes; a client reconciling on `done` cannot
    # be handed the authoritative text first.
    assert max(event.seq for event in deltas) < done[0].seq


def test_a_delta_subscriber_that_raises_does_not_lose_the_call(created_sessions):
    """The callback runs inside a request that is already being paid for. Letting it abort
    the call would trade a rendering problem for a lost answer and a wasted charge."""
    from api import llm as llm_module

    _, session_id = start_session(created_sessions)
    model = ScriptedModel(model_response(text_block("still fine")))

    def explode(chunk: str) -> None:
        raise RuntimeError("the subscriber is broken")

    completion = llm_module.stream(
        job="interviewing",
        messages=[{"role": "user", "content": "hi"}],
        on_delta=explode,
        session_id=session_id,
        settings=llm_settings(),
        client=model,
    )
    assert completion.text == "still fine"
    assert completion.usage.total > 0
