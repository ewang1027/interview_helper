"""The coding grader against real containers and the real corpus. Marked `sandbox`.

`test_grading_coding.py` fixes the arithmetic with a stub. This proves the whole path:
a corpus item's own tests, over HTTP, into the sandbox, back through the probe, out as a
score and a set of `concept_evidence` rows. It is deliberately built on `i.code.0002`,
whose reference solution and naive impostor are the pair docs/BUILDLOG.md measured when
the probe was calibrated.

The executor runs in-process here via `TestClient`, but the containers are real: this
exercises the same endpoint, the same driver and the same isolation a deployed executor
would apply.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.executor_client import ExecutorClient
from api.grading.coding import COMPLEXITY_RETENTION, grade_coding
from corpus.loader import load_items
from corpus.models import Item
from executor.main import app as executor_app

pytestmark = pytest.mark.sandbox

ITEM_ID = "i.code.0002"

# Passes every one of the item's tests — its stress cases top out at n=800, where a
# quadratic scan is still instant. Only the probe can tell this apart from the reference.
QUADRATIC = (
    "def pressure_spans(readings):\n"
    "    out = []\n"
    "    for i in range(len(readings)):\n"
    "        span, j = 1, i - 1\n"
    "        while j >= 0 and readings[j] <= readings[i]:\n"
    "            span += 1\n"
    "            j -= 1\n"
    "        out.append(span)\n"
    "    return out\n"
)


@pytest.fixture(scope="module")
def item() -> Item:
    return next(i for i in load_items() if i.id == ITEM_ID)


@pytest.fixture(scope="module")
def runner() -> ExecutorClient:
    return ExecutorClient(http=TestClient(executor_app))


def test_the_reference_solution_scores_full_marks(item: Item, runner: ExecutorClient) -> None:
    reference = (item.grading or {})["reference_solutions"]["python"]
    grade = grade_coding(item, reference, runner=runner)

    assert grade.status == "graded", grade.detail
    assert (grade.passed, grade.total) == (grade.total, grade.total)
    assert grade.complexity == "matches", grade.detail
    assert grade.score == pytest.approx(1.0)
    assert [e.concept_id for e in grade.evidence] == list(item.concepts)


def test_the_tests_alone_do_not_catch_the_quadratic_submission(
    item: Item, runner: ExecutorClient
) -> None:
    """Stated separately from the test below because it is the premise the probe exists
    for. If a future stress case ever grew large enough to time this out, the next test
    would still pass for the wrong reason."""
    grade = grade_coding(item, QUADRATIC, runner=runner)
    assert grade.correctness == pytest.approx(1.0), grade.detail


def test_the_probe_costs_the_quadratic_submission_a_quarter_of_its_score(
    item: Item, runner: ExecutorClient
) -> None:
    grade = grade_coding(item, QUADRATIC, runner=runner)

    assert grade.complexity == "slower_than_target", grade.detail
    assert grade.complexity_slope is not None and grade.complexity_slope > 1.65
    assert grade.score == pytest.approx(COMPLEXITY_RETENTION)


def test_a_do_nothing_stub_scores_zero_and_still_writes_evidence(
    item: Item, runner: ExecutorClient
) -> None:
    """A real zero is a measurement, and mastery should hear about it. This is the case
    a failed grading must not be confused with."""
    grade = grade_coding(item, "def pressure_spans(readings):\n    return None\n", runner=runner)

    assert grade.status == "graded"
    assert grade.score == pytest.approx(0.0)
    assert grade.evidence and all(e.score == 0.0 for e in grade.evidence)


def test_an_infinite_loop_is_a_failed_grading_and_writes_nothing(
    item: Item, runner: ExecutorClient
) -> None:
    """docs/GRADING.md: a missing grade is visible, a fabricated one corrupts mastery."""
    grade = grade_coding(
        item, "def pressure_spans(readings):\n    while True:\n        pass\n", runner=runner
    )

    assert grade.status == "failed"
    assert grade.outcome == "timeout"
    assert grade.score is None
    assert grade.evidence == ()
