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

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api.auth import SESSION_COOKIE, session_token
from api.db import get_engine
from api.main import app
from api.mastery import recompute
from api.models import Artifact, ConceptEvidence, Grading, InterviewSession, LlmCall
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
    app.dependency_overrides[get_settings] = auth_settings
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
            # Before the sessions themselves: `llm_calls.session_id` is a foreign key, so a
            # test whose session made a model call cannot have its session deleted first.
            db.exec(delete(LlmCall).where(col(LlmCall.session_id).in_(session_ids)))
            db.exec(delete(ConceptEvidence).where(col(ConceptEvidence.session_id).in_(session_ids)))
            db.exec(delete(Artifact).where(col(Artifact.session_id).in_(session_ids)))
            db.exec(delete(InterviewSession).where(col(InterviewSession.id).in_(session_ids)))
            db.commit()
        recompute(db, single_user(db).id)


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
