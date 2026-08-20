"""The rating and scheduling arithmetic. Hermetic — no database, no evidence rows.

These pin the properties the projection depends on. The scheduler ones matter most: they
are about the *library's configuration*, which is the kind of thing a later reader
"simplifies" back to defaults without seeing what it costs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fsrs import Card, Rating, Scheduler

from api.mastery import (
    CALIBRATION_OBSERVATIONS,
    K_MAX,
    K_MIN,
    SCHEDULER,
    expected_score,
    is_calibrating,
    k_factor,
    normalized_ability,
    rating_for,
)

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def test_an_even_match_expects_half_a_point():
    assert expected_score(1500, 1500) == pytest.approx(0.5)


def test_four_hundred_points_of_advantage_is_about_ninety_percent():
    assert expected_score(1900, 1500) == pytest.approx(0.909, abs=0.001)
    assert expected_score(1100, 1500) == pytest.approx(0.091, abs=0.001)


def test_expectations_are_symmetric():
    assert expected_score(1700, 1300) + expected_score(1300, 1700) == pytest.approx(1.0)


def test_early_evidence_moves_an_estimate_faster_than_late_evidence():
    assert k_factor(0) == pytest.approx(K_MAX)
    assert k_factor(0) > k_factor(4) > k_factor(16)


def test_k_never_falls_to_zero():
    """Skill decays. An estimate that stops moving stops being a measurement."""
    assert k_factor(10_000) == pytest.approx(K_MIN)


def test_a_concept_is_calibrating_until_it_has_been_seen_enough():
    assert is_calibrating(0)
    assert is_calibrating(CALIBRATION_OBSERVATIONS - 1)
    assert not is_calibrating(CALIBRATION_OBSERVATIONS)


def test_ability_normalises_into_the_unit_interval_and_clamps():
    assert normalized_ability(600) == pytest.approx(0.0)
    assert normalized_ability(2800) == pytest.approx(1.0)
    assert normalized_ability(200) == 0.0
    assert normalized_ability(4000) == 1.0


def test_scores_map_onto_the_four_grades_in_order():
    assert rating_for(0.0) is Rating.Again
    assert rating_for(0.49) is Rating.Again
    assert rating_for(0.5) is Rating.Hard
    assert rating_for(0.8) is Rating.Good
    assert rating_for(1.0) is Rating.Easy


def test_the_scheduler_is_deterministic():
    """The whole design rests on "the projection can be rebuilt from the evidence". FSRS
    enables interval fuzzing by default, and a fuzzed schedule cannot be rebuilt — the
    same review twice gives two answers."""
    first, _ = SCHEDULER.review_card(Card(), Rating.Good, review_datetime=NOW)
    second, _ = SCHEDULER.review_card(Card(), Rating.Good, review_datetime=NOW)
    assert first.due == second.due
    assert first.stability == second.stability


def test_fuzzing_would_break_that_and_this_is_what_it_looks_like():
    """The negative control for the line above. Kept because "fuzzing off" reads like a
    preference until you see it produce five different answers to one question."""
    fuzzed = Scheduler(enable_fuzzing=True, learning_steps=(), relearning_steps=())
    dues = {
        fuzzed.review_card(Card(stability=50.0, difficulty=5.0), Rating.Good, review_datetime=NOW)[
            0
        ].due
        for _ in range(5)
    }
    assert len(dues) > 1


def test_a_first_review_is_scheduled_in_days_not_minutes():
    """FSRS's flashcard defaults re-show a card after 60 seconds. A concept in a mock
    interview is not re-drilled a minute later, and a due date always in the past would
    make every concept look permanently overdue."""
    card, _ = SCHEDULER.review_card(Card(), Rating.Good, review_datetime=NOW)
    assert card.due - NOW >= timedelta(days=1)


def test_failing_shortens_the_interval_and_succeeding_lengthens_it():
    good, _ = SCHEDULER.review_card(Card(), Rating.Good, review_datetime=NOW)
    better, _ = SCHEDULER.review_card(good, Rating.Good, review_datetime=good.due)
    lapsed, _ = SCHEDULER.review_card(better, Rating.Again, review_datetime=better.due)

    assert better.stability > good.stability
    assert lapsed.stability < better.stability
