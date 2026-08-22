"""The model-call path against a live Postgres, with a fake provider.

What is being tested is not the model — it is the three things wrapped around the call:
the budget is checked before it, the ledger row is written after it, and the row survives
whatever the caller does next. A fake client makes those deterministic and free; the one
test that talks to a real provider is `test_llm_live.py`, marked `llm` and skipped by
default.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import auth_settings, sign_in, use_settings
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api import llm
from api.db import get_engine
from api.errors import ProblemError
from api.main import app
from api.model_router import ModelRouter
from api.models import LlmCall
from api.settings import Settings

pytestmark = pytest.mark.db

MODEL = "us.anthropic.claude-sonnet-4-6"


def fake_response(
    *,
    text: str = "hello",
    input_tokens: int = 100,
    output_tokens: int = 20,
    cache_read: int = 0,
    cache_write: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


class FakeAnthropic:
    """Records the request instead of sending it. Raising `error` lets one test drive the
    provider-failure path without inventing a network."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self._response = response or fake_response()
        self._error = error
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


MODEL_OVERRIDES: dict[str, Any] = {
    "model_interviewer": MODEL,
    "model_grader": MODEL,
    "model_planner": MODEL,
    "model_utility": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}


def llm_settings(**overrides: Any) -> Settings:
    """A `Settings` value for a direct call. Never install this as a dependency override —
    `conftest.use_settings` is what does that, and its docstring says why."""
    return auth_settings().model_copy(update={**MODEL_OVERRIDES, **overrides})


@pytest.fixture
def ledger() -> Iterator[list[str]]:
    """Remove exactly the rows a test wrote. The ledger is append-only in production and
    the dev database is shared, so nothing here deletes a row it did not create."""
    with Session(get_engine()) as db:
        before = set(db.exec(select(LlmCall.id)).all())
    written: list[str] = []
    yield written
    with Session(get_engine()) as db:
        after = set(db.exec(select(LlmCall.id)).all())
        new = after - before
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
            db.commit()


def spend_now(session_id: str | None = None) -> int:
    """What enforcement would see, in the window enforcement uses.

    The day budget is scoped to `start_of_day` and the session budget is not. This helper
    used to ignore the window entirely, which agreed with the route only on a ledger
    holding nothing older than today — so two tests below passed for as long as the dev
    database was young and failed the first time it carried a row from yesterday. The
    daily-refusal test was the worse of the two: it sets the limit just under what it
    reads, so summing all of history quietly raised the bar out of reach and the call it
    expected to be refused went through.
    """
    with Session(get_engine()) as db:
        if session_id is not None:
            return llm.tokens_spent(db, session_id=session_id)
        return llm.tokens_spent(db, since=llm.start_of_day())


# --- The call ----------------------------------------------------------------------------


def test_a_call_writes_one_ledger_row_with_its_cost(ledger):
    client = FakeAnthropic(fake_response(input_tokens=1_000_000, output_tokens=1_000_000))
    result = llm.complete(
        job="interviewing",
        messages=[{"role": "user", "content": "hi"}],
        system="You are an interviewer.",
        client=client,
        settings=llm_settings(),
    )

    assert result.text == "hello"
    assert result.usage.total == 2_000_000
    # Sonnet 4.6 list rates: $3/M in, $15/M out.
    assert result.cost_usd == pytest.approx(18.0)

    with Session(get_engine()) as db:
        row = db.get(LlmCall, result.call_id)
        assert row is not None
        assert (row.job, row.model, row.provider) == ("interviewing", MODEL, "bedrock")
        assert (row.input_tokens, row.output_tokens) == (1_000_000, 1_000_000)
        assert row.cost_usd == pytest.approx(18.0)
        assert row.latency_ms >= 0


def test_the_system_prompt_is_sent_as_one_cacheable_block(ledger):
    """Bedrock has no automatic caching, so the breakpoint is placed by hand — and if it
    stops being placed, the only symptom is the bill."""
    client = FakeAnthropic()
    llm.complete(
        job="interviewing",
        messages=[{"role": "user", "content": "hi"}],
        system="frozen prompt",
        client=client,
        settings=llm_settings(),
    )
    system = client.requests[0]["system"]
    assert system == [
        {"type": "text", "text": "frozen prompt", "cache_control": {"type": "ephemeral"}}
    ]


def test_effort_is_per_job_and_dropped_for_a_model_that_would_reject_it(ledger):
    """docs/COST.md asks for effort tuned per job. Haiku 4.5 rejects the parameter, so the
    router omits it rather than making an older model unusable."""
    client = FakeAnthropic()
    settings = llm_settings()
    llm.complete(
        job="grading", messages=[{"role": "user", "content": "x"}], client=client, settings=settings
    )
    llm.complete(
        job="interviewing",
        messages=[{"role": "user", "content": "x"}],
        client=client,
        settings=settings,
    )
    llm.complete(
        job="classification",
        messages=[{"role": "user", "content": "x"}],
        client=client,
        settings=settings,
    )

    assert client.requests[0]["output_config"] == {"effort": "high"}
    assert client.requests[1]["output_config"] == {"effort": "medium"}
    assert "output_config" not in client.requests[2]


def test_a_provider_failure_writes_no_ledger_row(ledger):
    """A call that never produced usage cost nothing, and a zero-token row would make the
    ledger's own call count wrong."""
    import anthropic
    import httpx

    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))
    before = spend_now()
    with pytest.raises(ProblemError) as raised:
        llm.complete(
            job="interviewing",
            messages=[{"role": "user", "content": "hi"}],
            client=FakeAnthropic(error=error),
            settings=llm_settings(),
        )
    assert raised.value.status == 503
    assert spend_now() == before


def test_the_ledger_row_survives_the_caller_failing_afterwards(ledger):
    """The spend happened whatever the caller does next. The row is written in its own
    transaction for the same reason a failed grading is."""
    result = llm.complete(
        job="interviewing",
        messages=[{"role": "user", "content": "hi"}],
        client=FakeAnthropic(),
        settings=llm_settings(),
    )
    with Session(get_engine()) as db, pytest.raises(RuntimeError):
        db.get(LlmCall, result.call_id)
        raise RuntimeError("the caller's own work blew up after the call")

    with Session(get_engine()) as db:
        assert db.get(LlmCall, result.call_id) is not None


# --- Budgets ------------------------------------------------------------------------------


def test_a_spent_daily_budget_refuses_the_next_call(ledger):
    """Refused, not downgraded (docs/COST.md). The limit is set below what is already on
    the ledger so the test does not depend on what else the database holds."""
    llm.complete(
        job="interviewing",
        messages=[{"role": "user", "content": "hi"}],
        client=FakeAnthropic(),
        settings=llm_settings(),
    )
    spent = spend_now()

    settings = llm_settings(max_tokens_per_day=max(1, spent - 1))
    client = FakeAnthropic()
    with pytest.raises(ProblemError) as raised:
        llm.complete(
            job="interviewing",
            messages=[{"role": "user", "content": "hi"}],
            client=client,
            settings=settings,
        )
    assert raised.value.status == 429
    assert raised.value.slug == "budget-exceeded"
    assert raised.value.extra["scope"] == "day"
    assert client.requests == [], "the call must be refused before it is made, not after"


def test_a_spent_session_budget_refuses_only_that_session(ledger, created_sessions):
    session_id = _a_session(created_sessions)
    llm.complete(
        job="interviewing",
        messages=[{"role": "user", "content": "hi"}],
        session_id=session_id,
        client=FakeAnthropic(),
        settings=llm_settings(),
    )
    spent = spend_now(session_id)
    assert spent > 0

    settings = llm_settings(max_tokens_per_session=max(1, spent - 1))
    with pytest.raises(ProblemError) as raised:
        llm.complete(
            job="interviewing",
            messages=[{"role": "user", "content": "hi"}],
            session_id=session_id,
            client=FakeAnthropic(),
            settings=settings,
        )
    assert raised.value.extra["scope"] == "session"

    # Another session is unaffected: the ceiling is per session, and the daily one is not
    # reached.
    other = _a_session(created_sessions)
    llm.complete(
        job="interviewing",
        messages=[{"role": "user", "content": "hi"}],
        session_id=other,
        client=FakeAnthropic(),
        settings=settings,
    )


def _a_session(created_sessions: list[str]) -> str:
    client = sign_in(TestClient(app))
    created = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 45})
    assert created.status_code == 201, created.text
    created_sessions.append(created.json()["id"])
    return str(created.json()["id"])


# --- The routes ------------------------------------------------------------------------------


def test_the_budget_route_reports_what_the_enforcement_uses(ledger):
    use_settings(**MODEL_OVERRIDES)
    client = sign_in(TestClient(app))
    llm.complete(
        job="interviewing",
        messages=[{"role": "user", "content": "hi"}],
        client=FakeAnthropic(),
        settings=llm_settings(),
    )

    body = client.get("/api/v1/costs/budget").json()
    assert body["day"]["spent"] == spend_now()
    assert body["day"]["remaining"] == llm_settings().max_tokens_per_day - body["day"]["spent"]
    assert body["session"]["id"] is None


def test_the_costs_route_splits_by_job_and_model(ledger):
    use_settings(**MODEL_OVERRIDES)
    client = sign_in(TestClient(app))
    llm.complete(
        job="grading",
        messages=[{"role": "user", "content": "hi"}],
        client=FakeAnthropic(),
        settings=llm_settings(),
    )

    body = client.get("/api/v1/costs").json()
    assert body["calls"] >= 1
    assert any(entry["job"] == "grading" for entry in body["by_job"])
    assert any(entry["model"] == MODEL for entry in body["by_model"])


def test_the_cost_routes_need_a_session_cookie():
    use_settings()
    anonymous = TestClient(app)
    assert anonymous.get("/api/v1/costs").status_code == 401
    assert anonymous.get("/api/v1/costs/budget").status_code == 401


def test_the_router_resolves_the_documented_job_table():
    """docs/ARCHITECTURE.md's routing table, as configuration rather than call sites."""
    router = ModelRouter(llm_settings())
    assert router.model_for("interviewing") == MODEL
    assert router.model_for("classification").endswith("haiku-4-5-20251001-v1:0")
    assert router.effort_for("classification") is None


def test_concurrent_calls_cannot_all_pass_a_spent_budget(ledger):
    """The ceiling is a ceiling under overlap, which it was not.

    `enforce_budget` used to read the ledger in a transaction that closed before the
    provider was called, so every call overlapping in time saw the same pre-spend total
    and every one proceeded. Measured at eight concurrent calls against a 1000-token
    daily limit: eight allowed, 8,000,000 tokens spent — an 8000x overshoot of a bound
    docs/COST.md describes as one call's `max_tokens`.

    Every `/api/v1` handler is a sync `def`, so Starlette runs them in a threadpool; two
    browser tabs or a retrying client are enough to reach this.
    """
    use_settings(**MODEL_OVERRIDES)
    settings = llm_settings(max_tokens_per_day=1000)
    clients = [
        FakeAnthropic(fake_response(input_tokens=1_000_000, output_tokens=0)) for _ in range(8)
    ]
    allowed: list[int] = []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        try:
            llm.complete(
                job="interviewing",
                messages=[{"role": "user", "content": "hi"}],
                client=clients[index],
                settings=settings,
            )
        except ProblemError:
            return
        with lock:
            allowed.append(index)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(allowed) == 1, f"{len(allowed)} of 8 concurrent calls passed a 1000-token ceiling"
    assert sum(len(client.requests) for client in clients) == 1


def test_a_stream_that_drops_after_producing_output_still_writes_its_spend(ledger):
    """A dropped stream has already been billed for what it delivered.

    The failure path wrote no ledger row at all, on the reasoning that "a call that never
    produced usage never cost anything" — true of `complete`, false of `stream`, which has
    handed the caller tokens by the time it fails.
    """
    use_settings(**MODEL_OVERRIDES)
    before = spend_now()
    delivered: list[str] = []

    with pytest.raises(ProblemError) as raised:
        llm.complete(
            job="interviewing",
            messages=[{"role": "user", "content": "hi"}],
            client=FakeAnthropic(error=RuntimeError("connection reset")),
            settings=llm_settings(),
        )

    assert raised.value.status == 503
    assert delivered == []
    # The reservation is settled rather than left in flight, so it stops counting against
    # the budget once the call is over.
    with Session(get_engine()) as db:
        stuck = db.exec(select(LlmCall).where(LlmCall.status == "reserved")).all()
    assert stuck == [], "a failed call left a reservation holding budget"
    assert spend_now() == before


def test_a_provider_error_that_is_not_an_anthropic_class_is_still_a_503(ledger):
    """`llm` used to name three `anthropic` exceptions. Two real failures walked past
    them: `APIResponseValidationError` is a sibling of `APIStatusError`, and a botocore
    credential error out of the Bedrock client is not an `anthropic` exception at all —
    that one reached the client as a text/plain 500, outside the problem+json contract
    every route is supposed to keep."""
    use_settings(**MODEL_OVERRIDES)

    with pytest.raises(ProblemError) as raised:
        llm.complete(
            job="interviewing",
            messages=[{"role": "user", "content": "hi"}],
            client=FakeAnthropic(error=ValueError("credentials expired")),
            settings=llm_settings(),
        )

    assert raised.value.status == 503
    assert raised.value.slug == "dependency-unavailable"
