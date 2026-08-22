"""Driver construction and result parsing. Pure — no Docker, so these run by default.

These matter because `parse_result` is where a bad run could quietly become a good score.
Each test below is aimed at one way that could happen.
"""

from __future__ import annotations

import json

import pytest

from executor.harness import RESULT_MARKER, build_driver, parse_result
from executor.protocol import ExecuteResponse

# Aliased on import: pytest tries to collect any class named Test* and warns that it
# cannot, because the pydantic model has an __init__. The model's name is right for the
# contract; the alias just keeps the collector out of it.
from executor.protocol import TestCase as Case

CASES = (
    Case(input=(1, 2), expected=3, name="adds", kind="example"),
    Case(input=(0, 0), expected=0, name="zeros", kind="edge"),
)


def _ok(detail: str) -> ExecuteResponse:
    return ExecuteResponse(outcome="ok", detail=detail)


def _marker(**payload: object) -> str:
    return RESULT_MARKER + json.dumps(payload)


def test_driver_embeds_the_source_and_every_selected_case() -> None:
    program = build_driver("def add(a, b):\n    return a + b\n", "add", CASES)
    assert "def add(a, b):" in program
    assert "adds" in program and "zeros" in program


def test_parses_a_clean_result() -> None:
    out = parse_result(_ok(_marker(passed=2, total=2, failures=[])), total=2)
    assert out.outcome == "ok"
    assert (out.passed, out.total) == (2, 2)
    assert out.is_gradeable


def test_carries_failure_kind_through() -> None:
    """docs/GRADING.md weights evidence by test kind, so the kind has to survive the
    round trip — a failure that loses it cannot be weighted correctly."""
    detail = _marker(
        passed=1,
        total=2,
        failures=[{"name": "zeros", "kind": "edge", "message": "expected 0, got 1"}],
    )
    out = parse_result(_ok(detail), total=2)
    assert out.passed == 1
    assert out.failures[0].kind == "edge"
    assert out.failures[0].name == "zeros"


def test_a_timeout_is_never_rescored_as_a_result() -> None:
    """The sandbox's verdict wins. Reading a timeout as 0/2 would write evidence of
    weakness for a run that never finished — docs/GRADING.md's "failure is a failure"."""
    out = parse_result(ExecuteResponse(outcome="timeout", detail="whatever"), total=2)
    assert out.outcome == "timeout"
    assert not out.is_gradeable
    assert out.passed == 0


def test_out_of_memory_is_preserved_too() -> None:
    out = parse_result(ExecuteResponse(outcome="out_of_memory"), total=2)
    assert out.outcome == "out_of_memory"
    assert not out.is_gradeable


def test_missing_entrypoint_becomes_a_harness_error() -> None:
    out = parse_result(_ok(_marker(error="no callable named 'add' was defined")), total=2)
    assert out.outcome == "harness_error"
    assert not out.is_gradeable
    assert "no callable" in out.detail


def test_exit_zero_with_no_marker_is_not_a_pass() -> None:
    """A candidate calling sys.exit(0), or output truncated past the cap, leaves a clean
    exit and no result line. Reading that as "no failures" would hand a full score to a
    program that never ran a single test."""
    out = parse_result(_ok("printed some debug output and stopped"), total=2)
    assert out.outcome == "harness_error"
    assert not out.is_gradeable
    assert out.passed == 0


def test_a_marker_printed_before_the_real_one_does_not_win() -> None:
    """The driver prints its line after every test has run, so the LAST marker is the
    authoritative one. Parsing the first match instead would let a candidate print a
    full score before the run even starts and be believed."""
    forged = _marker(passed=99, total=99, failures=[])
    genuine = _marker(
        passed=0, total=2, failures=[{"name": "adds", "kind": "example", "message": "x"}]
    )
    out = parse_result(_ok(forged + "\n" + genuine), total=2)
    assert (out.passed, out.total) == (0, 2), "a forged earlier marker was believed"


def test_a_corrupt_marker_line_is_skipped_not_fatal() -> None:
    """Truncated output can leave a half-written marker. Skipping back to the previous
    valid line beats raising, which would surface as a crash rather than a grading."""
    out = parse_result(
        _ok(_marker(passed=2, total=2, failures=[]) + "\n" + RESULT_MARKER + "{trunc"), total=2
    )
    assert out.outcome == "ok"
    assert (out.passed, out.total) == (2, 2)


def test_a_forged_marker_cannot_claim_more_passes_than_there_are_tests():
    """The result travels back on the same stdout the candidate can write to.

    docs/SECURITY.md scopes *result forgery* out — single user, the only person deceived
    is the one practising. What was not in scope is the blast radius: taking `total` from
    the payload let `{"passed": 10000, "total": 1}` through, `grade_coding` turned it into
    correctness 10000.0, and `mastery` applies `k * (score - expected)` with no clamp on
    the result — roughly 10^5 Elo on one concept, permanently, and reproduced faithfully
    by every replay. `total` now comes from the caller, which is `len(tests)`.
    """
    raw = ExecuteResponse(
        outcome="ok",
        passed=0,
        total=0,
        detail='##LEARN-RESULT {"passed": 10000, "total": 1, "failures": []}',
    )

    result = parse_result(raw, total=11)

    assert result.total == 11
    assert result.passed == 11  # clamped to the real count, not 10000


@pytest.mark.parametrize(
    "marker",
    [
        '##LEARN-RESULT {"total": 3}',  # no `passed`
        '##LEARN-RESULT {"passed": 1, "failures": [{"not": "a failure"}]}',
        "##LEARN-RESULT [1, 2, 3]",  # valid JSON, not an object
        '##LEARN-RESULT {"passed": "lots"}',
    ],
)
def test_a_marker_of_the_wrong_shape_fails_closed_rather_than_crashing(marker: str):
    """Valid JSON with the wrong shape used to raise out of the request handler, and a 500
    from the executor is read by the API as `unavailable` — which says nothing about the
    submission. That gave a candidate a reliable way to make their own grading disappear
    as an infrastructure fault. An existing test covered *invalid* JSON only."""
    result = parse_result(ExecuteResponse(outcome="ok", passed=0, total=0, detail=marker), total=11)

    assert result.outcome == "harness_error"
