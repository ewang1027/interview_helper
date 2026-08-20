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
from sqlmodel import Session, col, delete, select

from api.db import get_engine
from api.mastery import recompute
from api.models import Artifact, ConceptEvidence, Grading, InterviewSession
from api.users import current_user


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
            db.exec(delete(ConceptEvidence).where(col(ConceptEvidence.session_id).in_(session_ids)))
            db.exec(delete(Artifact).where(col(Artifact.session_id).in_(session_ids)))
            db.exec(delete(InterviewSession).where(col(InterviewSession.id).in_(session_ids)))
            db.commit()
        recompute(db, current_user(db).id)


@pytest.fixture
def created_sessions() -> Iterator[list[str]]:
    """Append every session id a test creates; teardown does the rest."""
    ids: list[str] = []
    yield ids
    _cleanup(ids)


@pytest.fixture
def user_id() -> str:
    with Session(get_engine()) as db:
        user = current_user(db)
        db.commit()
        return user.id


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A plain database session for tests that call service functions directly."""
    with Session(get_engine()) as db:
        yield db
        db.rollback()
