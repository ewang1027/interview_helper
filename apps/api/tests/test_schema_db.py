"""Schema round-trip against a live Postgres. Marked `db`: excluded from the
default run, run via `make test-db` after `make dev`.

These assert the two invariants the schema is actually responsible for enforcing —
everything else is column plumbing that a migration either applied or didn't.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from api.db import get_engine
from api.ids import new_id
from api.models import Concept, ConceptEvidence, PracticeProblem, PracticeSolve

pytestmark = pytest.mark.db


@pytest.fixture
def session():
    with Session(get_engine()) as s:
        yield s
        s.rollback()


@pytest.fixture
def concept(session):
    """The seeded taxonomy is already in the DB; grab any real concept id."""
    c = session.exec(select(Concept).limit(1)).first()
    assert c is not None, "run `make seed` first — the taxonomy must be loaded"
    return c


def test_practice_log_evidence_round_trips(session, concept):
    problem = PracticeProblem(
        title="Two Sum",
        url="https://leetcode.com/problems/two-sum/",
        source_site="leetcode",
        primary_concept_id=concept.id,
        status="active",
    )
    session.add(problem)
    session.flush()

    evidence = ConceptEvidence(
        concept_id=concept.id,
        source="practice_log",
        practice_problem_id=problem.id,
        score=1.0,
        confidence=0.5,
        grader_version="practice-log-v1",
    )
    session.add(evidence)
    session.flush()

    solve = PracticeSolve(
        problem_id=problem.id,
        review_number=0,
        is_success=True,
        concept_evidence_id=evidence.id,
    )
    session.add(solve)
    session.flush()

    assert solve.concept_evidence_id == evidence.id
    assert evidence.item_id is None and evidence.session_id is None


def test_evidence_requires_exactly_one_source(session, concept):
    """The CHECK constraint from docs/PRACTICE_LOG.md: an evidence row is either
    session-graded or practice-log, never both and never neither."""
    neither = ConceptEvidence(
        concept_id=concept.id,
        source="practice_log",
        score=1.0,
        confidence=0.5,
        grader_version="practice-log-v1",
    )
    session.add(neither)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_evidence_rejects_both_sources_set(session, concept):
    both = ConceptEvidence(
        id=new_id(),
        concept_id=concept.id,
        source="practice_log",
        item_id="i.code.0001",
        practice_problem_id=new_id(),
        score=1.0,
        confidence=0.5,
        grader_version="practice-log-v1",
    )
    session.add(both)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
