"""One real model call, and the cache assertion docs/COST.md has been owed since Phase 3.

Marked `llm`: it spends money and needs credentials, so it is deselected by default and
run deliberately —

    make test-llm        # needs credentials, a live Postgres, and model access

It uses whatever `MODEL_UTILITY` resolves to, so what it proves is that *this deployment's
configuration* can reach *this deployment's provider* — which is the failure it exists to
catch. A model the account cannot reach skips with the provider's own words rather than
failing, because "your AWS account has not been granted this model" is not a code defect.

The caching half is the one docs/COST.md asks for by name: "a CI assertion that repeated
identical-prefix requests report a non-zero `cache_read_input_tokens`". Cache invalidation
is silent and its only symptom is the bill, which makes it exactly the kind of thing that
has to be asserted rather than assumed.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlmodel import Session, col, delete, select

from api import llm
from api.agent import prompts
from api.db import get_engine
from api.errors import ProblemError
from api.model_router import ModelRouter
from api.models import LlmCall
from api.settings import Settings, get_settings

# Expired or absent AWS credentials surface as botocore errors, below the Anthropic SDK and
# so below `llm.complete`'s translation. They are an environment condition, not a defect,
# and the difference matters: this test skips on them and fails on everything else.
try:  # pragma: no cover - botocore arrives with anthropic[bedrock]
    from botocore.exceptions import BotoCoreError, ClientError

    CREDENTIAL_ERRORS: tuple[type[BaseException], ...] = (BotoCoreError, ClientError)
except ImportError:  # pragma: no cover
    CREDENTIAL_ERRORS = ()

# `llm` only, deliberately not `db` as well: this needs a live Postgres for the ledger, but
# marking it `db` would put real spend inside `make test-db`, which is run constantly.
# Selection and requirements are different things, and only the marker controls selection.
pytestmark = pytest.mark.llm

# Comfortably over every current model's minimum cacheable prefix, and boring enough that
# the model has nothing to do with it.
FROZEN_PREFIX = (
    "You are a test fixture for a mock-interview trainer. "
    "Answer with exactly one word and never explain yourself.\n"
) + "".join(
    f"Reference note {i}: this line exists only to make the prefix long enough.\n"
    for i in range(400)
)


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def ledger() -> Iterator[None]:
    with Session(get_engine()) as db:
        before = set(db.exec(select(LlmCall.id)).all())
    yield
    with Session(get_engine()) as db:
        new = set(db.exec(select(LlmCall.id)).all()) - before
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
            db.commit()


def call(settings: Settings, question: str) -> llm.Completion:
    model = ModelRouter(settings).model_for("classification")
    try:
        return llm.complete(
            job="classification",
            system=FROZEN_PREFIX,
            messages=[{"role": "user", "content": question}],
            max_tokens=16,
            settings=settings,
        )
    except ProblemError as exc:  # pragma: no cover - depends on the account
        if exc.status != 503:
            raise  # a refused budget is this system's own doing, and a real failure here
        pytest.skip(f"{settings.model_provider} cannot serve {model}: {exc.detail}")
    except CREDENTIAL_ERRORS as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"no usable {settings.model_provider} credentials: {exc}")


def test_a_real_call_answers_and_lands_on_the_ledger(settings, ledger):
    result = call(settings, "Reply with the single word: ok")

    assert result.text.strip(), "the provider answered with no text"
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0
    assert result.latency_ms > 0

    with Session(get_engine()) as db:
        row = db.get(LlmCall, result.call_id)
        assert row is not None
        assert row.model == ModelRouter(settings).model_for("classification")
        assert row.provider == settings.model_provider
        assert row.input_tokens == result.usage.input_tokens
        # Priced, not merely recorded: an unpriced model writes $0 and a warning, and a
        # ledger of zeros is indistinguishable from free work.
        assert row.cost_usd > 0


def test_an_identical_prefix_is_served_from_cache(settings, ledger):
    """The assertion docs/COST.md names. A silent invalidator — a timestamp in the system
    prompt, an unsorted dict, a tool list that reorders — shows up here and nowhere else
    until the bill arrives."""
    first = call(settings, "Reply with the single word: one")
    second = call(settings, "Reply with the single word: two")

    written = first.usage.cache_write_tokens + second.usage.cache_write_tokens
    assert written > 0, "nothing was written to the cache; the breakpoint is not taking effect"
    assert second.usage.cache_read_tokens > 0, (
        "the second identical-prefix call read nothing from cache — "
        f"wrote {first.usage.cache_write_tokens}, read {second.usage.cache_read_tokens}"
    )


def test_a_real_interviewer_turn(settings, ledger):
    """The whole thing, once, for real: a session, a planned item, one candidate message,
    and a model that has to behave like an interviewer rather than a chatbot.

    Asserted loosely on purpose. Pinning phrasing would make this a test of one model's
    style; what matters is that it answered as the interviewer, that the turn was recorded,
    and that the call is on the ledger with the session attached to it.
    """
    from conftest import sign_in
    from fastapi.testclient import TestClient
    from sqlmodel import select

    from api import sessions as service
    from api.agent import loop
    from api.main import app
    from api.models import Artifact, ConceptEvidence, Grading, InterviewSession, Turn

    client = sign_in(TestClient(app))
    created = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 45})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]

    try:
        with Session(get_engine()) as db:
            session_row = db.get(InterviewSession, session_id)
            assert session_row is not None
            item = service.current_item(db, session_row)
            assert item is not None
            try:
                result = loop.run_turn(
                    db, session_row, item, prompts.opening_instruction(item), settings=settings
                )
            except ProblemError as exc:  # pragma: no cover - depends on the account
                if exc.status != 503:
                    raise
                pytest.skip(f"{settings.model_provider} did not answer: {exc.detail}")
            except CREDENTIAL_ERRORS as exc:  # pragma: no cover - depends on the machine
                pytest.skip(f"no usable {settings.model_provider} credentials: {exc}")

        assert result.text.strip(), "the interviewer said nothing"
        print(f"\n--- interviewer said:\n{result.text}\n")

        with Session(get_engine()) as db:
            turns = loop.transcript(db, session_id)
            assert [row.role for row in turns][:2] == ["candidate", "interviewer"]
            calls = db.exec(select(LlmCall).where(LlmCall.session_id == session_id)).all()
            assert len(calls) >= 1
            assert calls[0].job == "interviewing"
            assert calls[0].output_tokens > 0
    finally:
        with Session(get_engine()) as db:
            for model in (Turn, LlmCall, ConceptEvidence, Artifact, Grading):
                if model is Grading:
                    continue
                db.exec(delete(model).where(col(model.session_id) == session_id))
            db.exec(delete(InterviewSession).where(col(InterviewSession.id) == session_id))
            db.commit()
