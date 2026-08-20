"""The coding grader's arithmetic, with the executor stubbed out.

These fix the *rules* — what a complexity miss costs, what a hint costs, what a failed
run must never produce. `test_grading_coding_sandbox.py` proves the same grader against
real containers and the real corpus; this file is where the edge cases live, because a
stub can produce a timeout or an adversarial-only failure on demand and Docker cannot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import pytest

from api.executor_client import ProbeOutcome, RunFailure, RunResult
from api.grading.coding import (
    BASE_CONFIDENCE,
    COMPLEXITY_RETENTION,
    SECONDARY_CONFIDENCE,
    case_payloads,
    grade_coding,
    hint_penalty,
    hint_retention,
)
from corpus.models import Item

SOURCE = "def solve(xs):\n    return xs\n"

PROBE_SPEC = {
    "generator": "def make_input(n):\n    return [list(range(n))]\n",
    "sizes": [1000, 2000, 4000],
    "repeats": 3,
}


def make_item(**overrides: Any) -> Item:
    grading: dict[str, Any] = {
        "type": "tests",
        "languages": ["python"],
        "entrypoint": "solve",
        "tests": [
            {"input": [[1]], "expected": [1], "name": "one", "kind": "example"},
            {"input": [[2]], "expected": [2], "name": "two", "kind": "edge"},
            {"input": [[3]], "expected": [3], "name": "three", "kind": "adversarial"},
        ],
        "reference_solutions": {"python": SOURCE},
        "complexity_target": "O(n)",
        "complexity_probe": PROBE_SPEC,
    }
    grading.update(overrides.pop("grading", {}))
    payload: dict[str, Any] = {
        "id": "i.code.9001",
        "kind": "instance",
        "domain": "coding",
        "modality": "coding",
        "title": "A test-only item",
        "statement_md": "x" * 60,
        "concepts": ["sliding-window", "two-pointers", "big-o-analysis"],
        "primary_concept": "sliding-window",
        "difficulty": {"band": "medium", "elo": 1400},
        "sources": [
            {
                "url": f"https://example.test/{n}",
                "retrieved_at": date(2026, 8, 1),
                "evidence": n * 30,
            }
            for n in ("a", "b")
        ],
        "corpus_version": 1,
        "archetype_id": "a.code.9001",
        "hints": ["one", "two", "three", "four"],
        "grading": grading,
    }
    payload.update(overrides)
    return Item.model_validate(payload)


class StubRunner:
    """Satisfies `CodeRunner` and counts what was asked of it."""

    def __init__(self, run: RunResult, probe: ProbeOutcome | None = None) -> None:
        self._run = run
        self._probe = probe or ProbeOutcome(verdict="inconclusive", detail="stub")
        self.probes = 0
        self.tests_sent: list[Mapping[str, Any]] = []

    def run_tests(
        self,
        *,
        source: str,
        entrypoint: str,
        tests: Sequence[Mapping[str, Any]],
        language: str = "python",
        test_selection: Sequence[str] = (),
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> RunResult:
        self.tests_sent = list(tests)
        return self._run

    def probe(
        self,
        *,
        source: str,
        entrypoint: str,
        generator: str,
        sizes: Sequence[int],
        target: str | None,
        language: str = "python",
        repeats: int = 5,
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> ProbeOutcome:
        self.probes += 1
        return self._probe


def ok(passed: int, total: int = 3, failures: tuple[RunFailure, ...] = ()) -> RunResult:
    return RunResult(outcome="ok", passed=passed, total=total, failures=failures)


def test_a_clean_pass_with_a_matching_curve_scores_one():
    runner = StubRunner(ok(3), ProbeOutcome(verdict="matches", slope=1.02, target="O(n)"))
    grade = grade_coding(make_item(), SOURCE, runner=runner)

    assert grade.status == "graded"
    assert grade.score == pytest.approx(1.0)
    assert grade.complexity == "matches"
    assert runner.probes == 1


def test_evidence_is_written_for_every_concept_the_item_names():
    grade = grade_coding(make_item(), SOURCE, runner=StubRunner(ok(3)))

    assert [e.concept_id for e in grade.evidence] == [
        "sliding-window",
        "two-pointers",
        "big-o-analysis",
    ]
    assert all(e.score == grade.score for e in grade.evidence)
    assert all(e.grader_version == grade.grader_version for e in grade.evidence)


def test_the_primary_concept_carries_the_stronger_claim():
    """The item is chiefly a measurement of one concept; the others are real evidence,
    softer. Uniform confidence would let an incidental concept move mastery as hard as
    the one the problem is actually about."""
    grade = grade_coding(make_item(), SOURCE, runner=StubRunner(ok(3)))
    primary, *secondary = grade.evidence

    assert primary.confidence == pytest.approx(BASE_CONFIDENCE)
    for row in secondary:
        assert row.confidence == pytest.approx(BASE_CONFIDENCE * SECONDARY_CONFIDENCE)


def test_a_confident_complexity_miss_costs_a_quarter_of_the_score():
    """The accepted-but-quadratic case: every test passes, so correctness says 1.0 and
    only the probe knows better."""
    runner = StubRunner(
        ok(3), ProbeOutcome(verdict="slower_than_target", slope=2.03, target="O(n)")
    )
    grade = grade_coding(make_item(), SOURCE, runner=runner)

    assert grade.score == pytest.approx(COMPLEXITY_RETENTION)
    assert grade.components["complexity_retention"] == pytest.approx(COMPLEXITY_RETENTION)


def test_an_inconclusive_curve_leaves_the_score_exactly_where_correctness_put_it():
    """`inconclusive` is not a middle score. Splitting the difference would write soft
    evidence of weakness on the strength of noise."""
    runner = StubRunner(ok(3), ProbeOutcome(verdict="inconclusive", slope=1.4, target="O(n)"))
    grade = grade_coding(make_item(), SOURCE, runner=runner)

    assert grade.score == pytest.approx(1.0)
    assert grade.complexity == "inconclusive"


def test_a_fast_wrong_solution_earns_nothing_from_the_probe():
    """A weighted *sum* of correctness and complexity would hand this submission a
    quarter of the marks for being quick. `return []` is O(1)."""
    runner = StubRunner(
        ok(0, failures=(RunFailure(name="one", kind="example", message="wrong"),)),
        ProbeOutcome(verdict="matches", slope=0.1, target="O(n)"),
    )
    grade = grade_coding(make_item(), SOURCE, runner=runner)

    assert grade.score == pytest.approx(0.0)


def test_the_probe_is_skipped_when_nothing_passed():
    """It can only confirm a zero, and it costs a full sandbox run to do it."""
    runner = StubRunner(ok(0, failures=(RunFailure(name="one", kind="example", message="x"),)))
    grade = grade_coding(make_item(), SOURCE, runner=runner)

    assert runner.probes == 0
    assert grade.complexity is None


def test_partial_credit_is_the_pass_fraction():
    runner = StubRunner(
        ok(2, failures=(RunFailure(name="three", kind="adversarial", message="x"),)),
        ProbeOutcome(verdict="matches", slope=1.0, target="O(n)"),
    )
    grade = grade_coding(make_item(), SOURCE, runner=runner)

    assert grade.correctness == pytest.approx(2 / 3)
    assert grade.score == pytest.approx(2 / 3)


def test_a_timeout_is_a_failed_grading_and_writes_no_evidence():
    """The distinction the whole protocol exists for: a run that never finished says
    nothing about the candidate, and a zero would say something false and permanent."""
    runner = StubRunner(RunResult(outcome="timeout", passed=0, total=3, detail="wall clock"))
    grade = grade_coding(make_item(), SOURCE, runner=runner)

    assert grade.status == "failed"
    assert grade.score is None
    assert grade.correctness is None
    assert grade.evidence == ()
    assert runner.probes == 0


def test_every_non_ok_outcome_fails_the_grading_rather_than_scoring_it():
    for outcome in ("timeout", "out_of_memory", "pid_limit", "compile_error", "harness_error"):
        runner = StubRunner(RunResult(outcome=outcome, passed=0, total=3))
        grade = grade_coding(make_item(), SOURCE, runner=runner)
        assert (grade.status, grade.score) == ("failed", None), outcome


def test_hints_compound_and_are_charged_against_what_was_earned():
    clean = grade_coding(make_item(), SOURCE, runner=StubRunner(ok(3)))
    hinted = grade_coding(make_item(), SOURCE, runner=StubRunner(ok(3)), hints_revealed=2)

    assert hinted.score == pytest.approx(clean.score * 0.95 * 0.90)
    assert hinted.components["hint_retention"] == pytest.approx(0.855)


def test_hints_can_never_drive_a_score_below_zero():
    runner = StubRunner(ok(0, failures=(RunFailure(name="one", kind="example", message="x"),)))
    grade = grade_coding(make_item(), SOURCE, runner=runner, hints_revealed=9)

    assert grade.score == pytest.approx(0.0)


def test_later_hints_cost_more_and_the_schedule_never_runs_out():
    assert hint_penalty(1) < hint_penalty(2) < hint_penalty(3) < hint_penalty(4)
    assert hint_penalty(9) == hint_penalty(4)
    assert hint_retention(0) == 1.0
    with pytest.raises(ValueError):
        hint_penalty(0)


def test_failing_only_adversarial_cases_is_softer_evidence_than_failing_an_example():
    """docs/GRADING.md ties the kind to confidence, not to the score: both submissions
    below got one case wrong, and both score the same. What differs is how much that
    reading is allowed to move mastery."""
    adversarial = grade_coding(
        make_item(),
        SOURCE,
        runner=StubRunner(ok(2, failures=(RunFailure(name="t", kind="adversarial", message="x"),))),
    )
    example = grade_coding(
        make_item(),
        SOURCE,
        runner=StubRunner(ok(2, failures=(RunFailure(name="t", kind="example", message="x"),))),
    )

    assert adversarial.score == pytest.approx(example.score)
    assert adversarial.evidence[0].confidence < example.evidence[0].confidence


def test_a_target_with_no_probe_is_reported_as_unmeasured_rather_than_assumed():
    item = make_item(grading={"complexity_probe": None})
    item = Item.model_validate(
        item.model_dump() | {"grading": {**(item.grading or {}), "complexity_probe": None}}
    )
    runner = StubRunner(ok(3))
    grade = grade_coding(item, SOURCE, runner=runner)

    assert runner.probes == 0
    assert grade.complexity is None
    assert "no complexity_probe" in grade.detail


def test_tests_travel_with_the_request_because_the_executor_holds_no_corpus():
    runner = StubRunner(ok(3))
    grade_coding(make_item(), SOURCE, runner=runner)

    assert [t["name"] for t in runner.tests_sent] == ["one", "two", "three"]
    assert runner.tests_sent[0]["kind"] == "example"


def test_unnamed_cases_are_named_the_same_way_ci_names_them():
    item = make_item()
    item = Item.model_validate(
        item.model_dump()
        | {
            "grading": {
                **(item.grading or {}),
                "tests": [{"input": [[1]], "expected": [1]}, {"input": [[2]], "expected": [2]}],
            }
        }
    )
    assert [t["name"] for t in case_payloads(item)] == ["test_0", "test_1"]
    assert [t["kind"] for t in case_payloads(item)] == ["edge", "edge"]


def test_an_item_this_grader_does_not_own_is_a_caller_bug():
    item = make_item()
    rubric = Item.model_validate(
        item.model_dump() | {"grading": {"type": "rubric", "criteria": []}, "modality": "design"}
    )
    with pytest.raises(ValueError, match="not graded by tests"):
        grade_coding(rubric, SOURCE, runner=StubRunner(ok(3)))


def test_a_language_the_item_does_not_declare_is_refused_before_anything_runs():
    runner = StubRunner(ok(3))
    with pytest.raises(ValueError, match="declares"):
        grade_coding(make_item(), SOURCE, runner=runner, language="cpp")
    assert runner.tests_sent == []
