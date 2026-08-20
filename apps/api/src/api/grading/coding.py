"""The deterministic coding grader — where counts and a growth curve become evidence.

docs/GRADING.md asks for "a weighted mix of correctness (dominant), complexity match, and
hint penalty". This is that mix. Four decisions shape what the numbers mean, and each one
is a place where the obvious implementation is wrong:

1. **The probe never adds points; it only takes them away.** A weighted *sum* of
   correctness and complexity hands a quarter of the marks to a submission that fails
   every test and returns instantly — `return []` is O(1). Complexity is therefore a
   multiplier on earned correctness, which is also what makes correctness "dominant" in
   the literal sense: it is the only term that can put points on the board.

2. **Only `slower_than_target` counts, and `inconclusive` is not a middle score.** An
   unmeasurable curve leaves the score exactly where correctness put it. Splitting the
   difference would write soft evidence of weakness on the strength of noise.

3. **The probe is skipped when nothing passed.** It exists to catch the
   accepted-but-quadratic solution; against a submission that already scores zero it can
   only confirm the zero, at the cost of a 60-second sandbox run per grading.

4. **A failed run is not a zero.** A timeout, an OOM kill or a missing entrypoint yields
   `status="failed"`, `score=None` and **no evidence rows**. docs/GRADING.md: a missing
   grade is visible, a fabricated one corrupts mastery permanently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from api.executor_client import CodeRunner, ExecutorClient, Language, RunFailure, Verdict
from corpus.models import Item

# Bumped whenever the arithmetic or the thresholds below change, so old evidence stays
# interpretable. Recorded on every `gradings` and `concept_evidence` row this produces.
GRADER_VERSION = "coding.deterministic@1"

# What a confident complexity miss leaves behind. The submission solved the problem, at
# the wrong cost — a quarter off, not a fail. Deliberately larger than any single hint:
# shipping the wrong algorithm is worse than needing a nudge toward the right one.
COMPLEXITY_RETENTION = 0.75

# Marginal cost of each hint, in order, compounding. Later hints reveal more, so they
# cost more. These are fractions of the score still on the table rather than absolute
# points, which is why no number of hints can drive a score below zero — and why a
# candidate who solves nothing is not punished twice for having asked.
# Taking all four leaves 0.95 * 0.90 * 0.85 * 0.80 = 0.58 of what was earned.
HINT_PENALTIES = (0.05, 0.10, 0.15, 0.20)

# A hidden test passing is a fact, not an opinion — the most reliable evidence the system
# produces. Rubric graders will sit well below this.
BASE_CONFIDENCE = 0.9

# docs/GRADING.md: "Failing an adversarial test is weaker evidence of weakness than
# failing an example one, and the confidence on the resulting evidence row reflects that."
# The asymmetry is deliberate: the kinds discount the *weakness* claim only. A full pass
# is BASE_CONFIDENCE whatever the suite looked like, because these items each carry ten
# or more cases across every kind, so "passed a trivial suite" is not a live risk. When
# thin suites exist, this is the constant that has to learn about them.
FAILURE_SOFTNESS: dict[str, float] = {
    "example": 1.0,
    "edge": 0.9,
    "stress": 0.75,
    "adversarial": 0.6,
}

# item.schema.json: an item is "chiefly a measurement of" its primary concept, and lists
# the others as concepts it also produces evidence for. Real evidence, softer claim.
SECONDARY_CONFIDENCE = 0.6


@dataclass(frozen=True)
class Evidence:
    """One `concept_evidence` row, minus the columns only the writer knows.

    `source`, `item_id` and `session_id` are filled in by the session layer; a grader
    that reached the database could not be re-run over an old artifact without writing
    duplicate history.
    """

    concept_id: str
    score: float
    confidence: float
    grader_version: str = GRADER_VERSION


@dataclass(frozen=True)
class CodingGrade:
    """The whole result: what happened, what it scored, and what it is evidence of."""

    status: Literal["graded", "failed"]
    item_id: str
    outcome: str
    score: float | None
    correctness: float | None
    passed: int
    total: int
    hints_revealed: int
    detail: str
    complexity: Verdict | None = None
    complexity_slope: float | None = None
    failures: tuple[RunFailure, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    grader_version: str = GRADER_VERSION
    components: dict[str, float] = field(default_factory=dict)

    def as_detail(self) -> dict[str, Any]:
        """The `gradings.detail` JSONB payload — enough to explain the score without
        re-running anything, which is what makes a grade auditable after the fact."""
        return {
            "status": self.status,
            "outcome": self.outcome,
            "passed": self.passed,
            "total": self.total,
            "correctness": self.correctness,
            "complexity": self.complexity,
            "complexity_slope": self.complexity_slope,
            "hints_revealed": self.hints_revealed,
            "components": self.components,
            "failures": [f.model_dump() for f in self.failures],
            "detail": self.detail,
        }


def hint_penalty(level: int) -> float:
    """Marginal cost of revealing hint `level` (1-indexed) — the `score_penalty` that
    docs/API.md's `hint.revealed` event carries, so the cost is visible when it is taken
    rather than discovered in the report. A fraction of the remaining score, not points.

    Items with more hints than the schedule keep paying the last, steepest rate.
    """
    if level < 1:
        raise ValueError("hint levels are 1-indexed")
    return HINT_PENALTIES[min(level, len(HINT_PENALTIES)) - 1]


def hint_retention(hints_revealed: int) -> float:
    """What fraction of an earned score survives `hints_revealed` hints.

    Hints are monotonic (docs/API.md: level N implies N-1 was given), so the count is
    enough — the levels taken are always 1..n.
    """
    retention = 1.0
    for level in range(1, hints_revealed + 1):
        retention *= 1.0 - hint_penalty(level)
    return retention


def confidence_from(failures: tuple[RunFailure, ...]) -> float:
    """How much to trust this reading as evidence about the concept."""
    if not failures:
        return BASE_CONFIDENCE
    softness = sum(FAILURE_SOFTNESS.get(f.kind, 1.0) for f in failures) / len(failures)
    return BASE_CONFIDENCE * softness


def case_payloads(item: Item) -> list[dict[str, Any]]:
    """The item's own cases, in the shape `/execute` takes.

    Not named `test_*`: pytest collects any importable callable with that prefix, so a
    helper named for what it does would have been silently gathered as a broken test.

    The executor holds no corpus (docs/SECURITY.md), so the tests travel with the
    request. Names are defaulted the same way `scripts/verify_reference_solutions.py`
    defaults them, so a failure is named identically in CI and in a real grading.
    """
    grading = item.grading or {}
    return [
        {
            "input": list(case.get("input", [])),
            "expected": case.get("expected"),
            "name": case.get("name") or f"test_{index}",
            "kind": case.get("kind", "edge"),
            "hidden": case.get("hidden", True),
        }
        for index, case in enumerate(grading.get("tests", []))
    ]


def _evidence_for(item: Item, score: float, confidence: float) -> tuple[Evidence, ...]:
    rows = [Evidence(item.primary_concept, score, confidence)]
    rows += [
        Evidence(concept, score, confidence * SECONDARY_CONFIDENCE)
        for concept in item.concepts
        if concept != item.primary_concept
    ]
    return tuple(rows)


def grade_coding(
    item: Item,
    source: str,
    *,
    runner: CodeRunner | None = None,
    hints_revealed: int = 0,
    language: Language = "python",
) -> CodingGrade:
    """Run `source` against `item`'s own tests and turn the result into evidence."""
    grading = item.grading or {}
    if grading.get("type") != "tests":
        raise ValueError(f"{item.id} is not graded by tests (type={grading.get('type')!r})")

    declared: list[str] = grading.get("languages") or []
    if language not in declared:
        # docs/API.md's 422: well-formed, but not a submission this item can grade.
        raise ValueError(f"{item.id} declares {declared}, not {language!r}")

    entrypoint = grading.get("entrypoint")
    if not entrypoint:
        raise ValueError(f"{item.id} has no grading.entrypoint")

    tests = case_payloads(item)
    if not tests:
        raise ValueError(f"{item.id} ships no tests")

    limits = grading.get("limits") or {}
    runner = runner or ExecutorClient()
    run = runner.run_tests(
        source=source,
        entrypoint=entrypoint,
        tests=tests,
        language=language,
        wall_ms=limits.get("wall_ms"),
        memory_mb=limits.get("memory_mb"),
    )

    if not run.is_gradeable or run.total == 0:
        return CodingGrade(
            status="failed",
            item_id=item.id,
            outcome=run.outcome,
            score=None,
            correctness=None,
            passed=run.passed,
            total=run.total,
            hints_revealed=hints_revealed,
            failures=run.failures,
            detail=run.detail or f"run ended in {run.outcome}",
        )

    correctness = run.passed / run.total

    probe_spec = grading.get("complexity_probe")
    target = grading.get("complexity_target")
    verdict: Verdict | None = None
    slope: float | None = None
    probe_detail = ""
    if correctness > 0 and probe_spec and target:
        probe = runner.probe(
            source=source,
            entrypoint=entrypoint,
            generator=probe_spec["generator"],
            sizes=probe_spec["sizes"],
            target=target,
            language=language,
            repeats=probe_spec.get("repeats", 5),
        )
        verdict, slope, probe_detail = probe.verdict, probe.slope, probe.detail

    complexity_retention = COMPLEXITY_RETENTION if verdict == "slower_than_target" else 1.0
    retention = hint_retention(hints_revealed)
    score = correctness * complexity_retention * retention
    confidence = confidence_from(run.failures)

    reasons = [f"{run.passed}/{run.total} tests passed"]
    if verdict:
        reasons.append(f"complexity {verdict}" + (f" (slope {slope:.2f})" if slope else ""))
        if probe_detail:
            reasons.append(probe_detail)
    elif target and not probe_spec:
        # docs/GRADING.md: a target with no probe is inert, and saying so beats leaving
        # the reader to assume the growth was checked.
        reasons.append(f"declares {target} but ships no complexity_probe — growth unmeasured")
    if hints_revealed:
        reasons.append(f"{hints_revealed} hint(s) taken, keeping {retention:.0%} of the score")

    return CodingGrade(
        status="graded",
        item_id=item.id,
        outcome=run.outcome,
        score=score,
        correctness=correctness,
        passed=run.passed,
        total=run.total,
        hints_revealed=hints_revealed,
        complexity=verdict,
        complexity_slope=slope,
        failures=run.failures,
        evidence=_evidence_for(item, score, confidence),
        detail="; ".join(reasons),
        components={
            "correctness": correctness,
            "complexity_retention": complexity_retention,
            "hint_retention": retention,
        },
    )
