"""The practice log's arithmetic and its request shape — no database, no model.

The scheduling rule is three lines of arithmetic and the reason it is tested separately is
that the interesting cases are the boundaries: a lapse that must not reset, a floor that
must hold, and a growth factor that has to compound rather than re-multiply the first
interval. The database tests exercise the flows; these pin the numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api import practice
from api.models import PracticeProblem


def _problem(*, primary: str | None, secondaries: list[str]) -> PracticeProblem:
    return PracticeProblem(
        title="t",
        url="u",
        source_site="other",
        primary_concept_id=primary,
        secondary_concept_ids=secondaries,
    )


def test_the_first_interval_is_measured_from_the_solve_not_from_now():
    """A problem you logged three days late is due tomorrow, not in three days."""
    solved = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    stability, due = practice.first_interval(solved)
    assert stability == practice.INITIAL_INTERVAL_DAYS
    assert (due - solved).days == 3


def test_a_successful_review_compounds_the_interval():
    """Compounds, rather than re-multiplying the first interval: the second successful
    re-solve has to be further out than the first, which is the whole point of spacing."""
    first = practice.next_interval(practice.INITIAL_INTERVAL_DAYS, success=True)
    second = practice.next_interval(first, success=True)
    assert first == pytest.approx(7.5)
    assert second == pytest.approx(18.75)


def test_a_lapse_halves_rather_than_resets():
    """A problem you missed on review is not a problem you never solved, and sending it
    back to three days would treat those the same."""
    assert practice.next_interval(20.0, success=False) == 10.0
    assert practice.next_interval(7.5, success=False) == 3.75


def test_the_interval_has_a_floor():
    """Otherwise repeated misses converge on "due again in four hours", which is a way of
    asking someone to re-solve a problem they have just failed."""
    assert practice.next_interval(1.5, success=False) == practice.MIN_INTERVAL_DAYS
    assert practice.next_interval(0.1, success=False) == practice.MIN_INTERVAL_DAYS


def test_the_response_schema_enumerates_the_whole_taxonomy():
    """Same reason the rubric grader enumerates an item's criteria: a tag that is not a
    concept cannot be expressed, rather than having to be caught afterwards — and
    `concept_evidence.concept_id` is a foreign key, so the alternative failure is an
    insert error mid-request."""
    schema = practice.response_schema()
    ids = schema["properties"]["primary_concept_id"]["enum"]
    assert set(ids) == practice.concept_ids()
    assert len(ids) > 150
    assert schema["additionalProperties"] is False
    # The four-secondary cap is *not* here: structured outputs reject `maxItems`, and this
    # test used to assert the keyword that made every real classification a 400. It is
    # enforced in `classify` now — see `test_a_classifier_returning_ten_secondaries_writes_four`.
    assert "maxItems" not in schema["properties"]["secondary_concept_ids"]


def test_the_taxonomy_is_the_cacheable_half_and_the_problem_is_not():
    """docs/COST.md's cache shape: the frozen taxonomy sits in the system block, which
    `api.llm` marks cacheable, and the volatile per-problem details go in the message. The
    other way round is a cache that never hits."""
    system = practice.taxonomy_prompt()
    assert "sliding-window" in system
    url = "https://example.invalid/p/8817"
    prompt = practice.build_prompt(
        title="Zigzag conversion redux", url=url, notes=None, difficulty_label="Easy"
    )
    assert "Zigzag conversion redux" in prompt and "Easy" in prompt
    assert url in prompt and url not in system


def test_the_prompt_carries_only_what_was_entered_by_hand():
    """docs/PRACTICE_LOG.md: this system stores pointers, never problem text. The prompt
    can only contain what the fields hold, and the fields are user-entered."""
    prompt = practice.build_prompt(
        title="Sliding Window Maximum",
        url="https://example.com/p/239",
        notes="Used a deque of indices.",
        difficulty_label=None,
    )
    assert "deque of indices" in prompt
    assert "Difficulty label" not in prompt


def test_evidence_splits_the_claim_the_way_the_coding_grader_does():
    """A problem is chiefly an exercise in one thing and really does exercise the others —
    the same split, and the same constant, rather than a second opinion about it."""
    problem = _problem(primary="sliding-window", secondaries=["two-pointers", "hash-map-counting"])
    rows = practice.evidence_rows(problem, success=True)
    assert rows[0] == ("sliding-window", practice.SOLVE_SCORE, practice.SOLVE_CONFIDENCE)
    assert [row[0] for row in rows[1:]] == ["two-pointers", "hash-map-counting"]
    assert all(row[2] < practice.SOLVE_CONFIDENCE for row in rows[1:])


def test_a_failed_re_solve_says_a_little_quietly():
    """Forgetting a problem is weaker evidence of not knowing a concept than failing a
    hidden test on it — so it is recorded, and it barely moves anything."""
    problem = _problem(primary="sliding-window", secondaries=[])
    ((_, score, confidence),) = practice.evidence_rows(problem, success=False)
    assert score == practice.LAPSE_SCORE < practice.SOLVE_SCORE
    assert confidence == practice.LAPSE_CONFIDENCE < practice.SOLVE_CONFIDENCE


def test_an_unclassified_problem_produces_no_evidence_at_all():
    """The gate, at the level below the flow: with no concept there is nothing to write
    against, and writing against a guess is what `concept_evidence` being immutable
    forbids."""
    assert practice.evidence_rows(_problem(primary=None, secondaries=[]), success=True) == []
