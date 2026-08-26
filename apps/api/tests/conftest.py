"""Shared fixtures for the API's database-backed tests.

**These run against the development database**, not a throwaway one, so nothing here
deletes rows it did not create. The teardown removes exactly the sessions a test made —
and then *replays* the projection, because `mastery` and `items.elo` are aggregates of
evidence that cannot be un-summed. Removing evidence without replaying would leave the
database in the one state the whole design says is impossible: a projection that does not
match the rows it is derived from, which would then fail the next test for reasons that
have nothing to do with that test.

If this database ever holds real practice history, these tests want a separate one: the
value assertions assume the concepts they touch start unmeasured.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api.auth import SESSION_COOKIE, session_token
from api.db import get_engine
from api.main import app
from api.mastery import recompute
from api.models import (
    Artifact,
    ConceptEvidence,
    Grading,
    IdempotencyKey,
    InterviewSession,
    LlmCall,
    Turn,
)
from api.settings import Settings, get_settings
from api.users import LOCAL_GITHUB_ID, single_user

# Every `/api/v1` route requires a session cookie (docs/API.md), so a test that drives the
# API needs one. It signs its own rather than logging in: the login flow is GitHub's, and
# `test_auth.py` is where that conversation is exercised.
TEST_SESSION_SECRET = "tests-only-never-a-deployed-secret"


def auth_settings() -> Settings:
    """The real configuration — the database URL a db test needs — with auth pinned to a
    secret the test also knows."""
    return get_settings().model_copy(
        update={"session_secret": TEST_SESSION_SECRET, "cookie_secure": False}
    )


def use_settings(**changes: Any) -> Settings:
    """Install a settings override for the app, and return what it will resolve to.

    Exists because assigning the builder itself — `dependency_overrides[get_settings] =
    make_settings`, where `make_settings(**overrides)` — has now cost three debugging
    sessions: FastAPI reads an override's signature like any other dependency, so
    `**overrides` becomes a *required query parameter* and every route answers
    `400 malformed-request` instead of anything to do with what the test was checking.
    A helper that closes over a built object cannot be called that way.
    """
    settings = auth_settings().model_copy(update=changes)
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


def sign_in(
    client: TestClient, user_id: str | None = None, *, github_id: int = LOCAL_GITHUB_ID
) -> TestClient:
    """Give a client the cookie, and the app the secret that verifies it.

    Defaults to the single user, which is who a database-backed test means: passing the id
    explicitly is for the tests that are *about* users — one client signed in as somebody
    else, checking it cannot read the first one's sessions.
    """
    if user_id is None:
        with Session(get_engine()) as db:
            user_id = single_user(db).id
    # `setdefault`, not assignment: a test that installed richer settings — a model id, a
    # lowered budget — must not have them silently replaced by signing a client in.
    app.dependency_overrides.setdefault(get_settings, auth_settings)
    client.cookies.set(
        SESSION_COOKIE,
        session_token(user_id=user_id, github_id=github_id, secret=TEST_SESSION_SECRET),
    )
    return client


def _cleanup(session_ids: list[str]) -> None:
    # The replay runs even when a test created no sessions: a test may write a `mastery`
    # row directly to set up a state that would take fifty sessions to reach honestly, and
    # leaving that behind would silently change what the next test measures.
    with Session(get_engine()) as db:
        if session_ids:
            artifacts = [
                row.id
                for row in db.exec(
                    select(Artifact).where(col(Artifact.session_id).in_(session_ids))
                ).all()
            ]
            if artifacts:
                db.exec(delete(Grading).where(col(Grading.artifact_id).in_(artifacts)))
            # Before the sessions themselves: `llm_calls.session_id` and `turns.session_id`
            # are foreign keys, so a session that took a turn or made a model call cannot
            # be deleted first.
            db.exec(delete(LlmCall).where(col(LlmCall.session_id).in_(session_ids)))
            db.exec(delete(Turn).where(col(Turn.session_id).in_(session_ids)))
            db.exec(delete(ConceptEvidence).where(col(ConceptEvidence.session_id).in_(session_ids)))
            db.exec(delete(Artifact).where(col(Artifact.session_id).in_(session_ids)))
            db.exec(delete(InterviewSession).where(col(InterviewSession.id).in_(session_ids)))
            db.commit()
        # Idempotency rows are keyed by (user, endpoint, key) and outlive the sessions
        # they created, so a test using a fixed key replays the *previous run's* response
        # — pointing at a session this teardown has already deleted. Measured: a suite
        # that passed on a clean database failed five ways on the second run. Cleared
        # user-wide for the same reason the replay below is unconditional.
        db.exec(delete(IdempotencyKey))
        db.commit()
        recompute(db, single_user(db).id)


# --- The guardrail ---------------------------------------------------------------------


ESCAPE_HATCH = "ALLOW_TESTS_ON_THIS_DATABASE"

# Every marker whose tests reach Postgres. `sandbox` is absent on purpose — those talk to
# Docker and never open a database connection.
DATABASE_MARKERS = ("db", "llm", "e2e")

# Set during collection; the canary below only plants rows when the run will touch Postgres.
_TOUCHES_THE_DATABASE = False

# The marker the canary's bait rows carry, so leftovers from a crashed run are identifiable
# and safe to clear.
CANARY = "__canary__"


# `trylast`: pytest applies `-m` deselection in this same hook, and without an ordering
# this one ran first and saw every collected item — so a plain `pytest -q`, whose `addopts`
# deselect every database marker, was refused for tests it was never going to run.
@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Refuse to run database tests against a database that is not a test database.

    The rule is the name: it must end in `_test`. `scripts/test_db.sh` derives that name
    from whatever `.env` configures, creates it, migrates and seeds it, and points these
    tests at it.

    This exists because the alternative failed. These tests ran against the development
    database on the promise that no fixture would delete a row it had not created — and on
    2026-08-26 one did, taking a real job-application list with it. The promise was
    reasonable and it was still only a promise: every teardown here is a hand-written
    `delete`, and one of them said "everything belonging to this user" where it meant "the
    rows this test made". A guard on the *connection* does not depend on getting each
    teardown right.

    The escape hatch is typed out where it is visible, like the `ALLOW_UNDOCUMENTED=1` on
    the docs gate — for the case where somebody genuinely wants these pointed elsewhere and
    has decided that on purpose.
    """
    global _TOUCHES_THE_DATABASE
    _TOUCHES_THE_DATABASE = any(
        any(item.get_closest_marker(name) for name in DATABASE_MARKERS) for item in items
    )
    if os.environ.get(ESCAPE_HATCH) == "1":
        return
    if not _TOUCHES_THE_DATABASE:
        return

    name = urlsplit(get_settings().database_url).path.lstrip("/")
    if name.endswith("_test"):
        return
    raise pytest.UsageError(
        f"refusing to run database tests against {name!r}: these tests delete rows, and "
        "this is not a test database.\n"
        "    bash scripts/test_db.sh          (or: make test-db)\n"
        f"  Override deliberately with {ESCAPE_HATCH}=1 if that is really what you want."
    )


@pytest.fixture(scope="session", autouse=True)
def _canary() -> Iterator[None]:
    """Plant a row in the tables these tests delete from, and check it is still there.

    The guardrail above stops a bad teardown reaching *real* data. This catches the bad
    teardown itself, on the run that introduces it, rather than on the day somebody notices
    something missing.

    Every teardown in this suite is a hand-written `delete`, and the failure they share is
    scope: `delete(X).where(X.user_id == the_local_user)` looks like cleanup and means
    "everything anyone ever made". A row planted before the suite and checked after is the
    cheapest detector there is, because a correctly scoped teardown cannot touch it and an
    over-broad one always does.

    The canary belongs to **the local user**, deliberately — that is the account whose rows
    a careless teardown sweeps up, so it is the account the bait has to be in.

    What is not watched, and why: `users` and `sessions`, because other tests count their
    rows and an extra one changes what those tests measure; `idempotency_keys`, cleared
    wholesale on purpose in `_cleanup`; and `mastery`, a projection this suite rebuilds by
    design. None of the four could be told apart from a bug by this method.
    """
    if not _TOUCHES_THE_DATABASE:
        yield
        return

    from api.models import JobApplication, JobApplicationEvent, LlmCall, PracticeProblem

    def clear(db: Session) -> None:
        """Remove a previous run's canary, so a crash does not block the next one."""
        stale = list(
            db.exec(select(JobApplication.id).where(col(JobApplication.company) == CANARY)).all()
        )
        if stale:
            db.exec(
                delete(JobApplicationEvent).where(
                    col(JobApplicationEvent.application_id).in_(stale)
                )
            )
            db.exec(delete(JobApplication).where(col(JobApplication.id).in_(stale)))
        db.exec(delete(PracticeProblem).where(col(PracticeProblem.title) == CANARY))
        db.exec(delete(LlmCall).where(col(LlmCall.job) == CANARY))
        db.commit()

    with Session(get_engine()) as db:
        clear(db)
        user = single_user(db)
        application = JobApplication(user_id=user.id, company=CANARY, role=CANARY)
        db.add(application)
        db.flush()
        db.add(
            JobApplicationEvent(
                application_id=application.id, sequence=0, stage="applied", note=CANARY
            )
        )
        db.add(PracticeProblem(title=CANARY, url=CANARY, source_site="other"))
        db.add(
            LlmCall(
                job=CANARY,
                model=CANARY,
                provider="anthropic",
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=0,
            )
        )
        db.commit()

    yield

    with Session(get_engine()) as db:
        survived = {
            "job_applications": select(JobApplication).where(col(JobApplication.company) == CANARY),
            "job_application_events": select(JobApplicationEvent).where(
                col(JobApplicationEvent.note) == CANARY
            ),
            "practice_problems": select(PracticeProblem).where(
                col(PracticeProblem.title) == CANARY
            ),
            "llm_calls": select(LlmCall).where(col(LlmCall.job) == CANARY),
        }
        missing = sorted(table for table, q in survived.items() if db.exec(q).first() is None)
        clear(db)

    if missing:
        raise AssertionError(
            "a teardown in this suite deleted rows it did not create, in: "
            + ", ".join(missing)
            + ". A cleanup fixture is scoped to a whole table or a whole user instead of to "
            "the rows its own test made — find it before it reaches a real database."
        )


@pytest.fixture(autouse=True)
def _no_leaked_overrides() -> Iterator[None]:
    """`app.dependency_overrides` is process-global. `sign_in` writes to it, so without
    this a module that signed in would hand its test secret to every module after it."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def created_sessions() -> Iterator[list[str]]:
    """Append every session id a test creates; teardown does the rest."""
    ids: list[str] = []
    yield ids
    _cleanup(ids)


@pytest.fixture
def user_id() -> str:
    with Session(get_engine()) as db:
        user = single_user(db)
        db.commit()
        return user.id


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A plain database session for tests that call service functions directly."""
    with Session(get_engine()) as db:
        yield db
        db.rollback()
