"""`POST /execute` end to end, against real Docker. Marked `sandbox`.

The unit tests in `test_harness.py` prove the parsing; these prove the wiring — that a
real container run produces the outcome the caller will actually record. The two most
important cases here are the ones where a *failed run* must not become a *score*.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from executor.main import app

pytestmark = pytest.mark.sandbox

client = TestClient(app)

ADD_TESTS = [
    {"input": [1, 2], "expected": 3, "name": "adds", "kind": "example"},
    {"input": [0, 0], "expected": 0, "name": "zeros", "kind": "edge"},
    {"input": [-1, -2], "expected": -3, "name": "negatives", "kind": "edge"},
]


def _execute(source: str, **overrides: object) -> dict:
    body: dict = {
        "language": "python",
        "source": source,
        "entrypoint": "add",
        "tests": ADD_TESTS,
    }
    body.update(overrides)
    resp = client.post("/execute", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_correct_solution_passes_every_test() -> None:
    body = _execute("def add(a, b):\n    return a + b\n")
    assert body["outcome"] == "ok"
    assert (body["passed"], body["total"]) == (3, 3)
    assert body["failures"] == []


def test_a_wrong_solution_reports_which_tests_failed_and_their_kind() -> None:
    """The kind has to survive to the caller: docs/GRADING.md weights evidence by it."""
    body = _execute("def add(a, b):\n    return 3\n")
    assert body["outcome"] == "ok"
    assert body["passed"] == 1
    failed = {f["name"]: f["kind"] for f in body["failures"]}
    assert failed == {"zeros": "edge", "negatives": "edge"}


def test_an_infinite_loop_is_a_timeout_not_a_zero() -> None:
    """The distinction this whole protocol exists for. A zero would write evidence of
    weakness against a concept the candidate may know perfectly well."""
    body = _execute("def add(a, b):\n    while True:\n        pass\n", wall_ms=2000)
    assert body["outcome"] == "timeout"
    assert body["passed"] == 0


def test_an_allocation_bomb_is_out_of_memory_not_a_zero() -> None:
    body = _execute(
        "def add(a, b):\n    x = bytearray(2_000_000_000)\n    return a + b\n",
        memory_mb=256,
    )
    assert body["outcome"] == "out_of_memory"
    assert body["passed"] == 0


def test_a_solution_that_never_defines_the_entrypoint_is_a_harness_error() -> None:
    body = _execute("def something_else(a, b):\n    return a + b\n")
    assert body["outcome"] == "harness_error"
    assert "no callable" in body["detail"]


def test_a_solution_that_exits_early_does_not_score() -> None:
    """sys.exit(0) at import leaves a clean exit and no result line. Reading that as
    'no failures' would hand a full score to a program that ran nothing."""
    body = _execute("import sys\nsys.exit(0)\n\ndef add(a, b):\n    return a + b\n")
    assert body["outcome"] == "harness_error"
    assert body["passed"] == 0


def test_test_selection_runs_only_the_named_cases() -> None:
    body = _execute("def add(a, b):\n    return a + b\n", test_selection=["zeros"])
    assert body["outcome"] == "ok"
    assert (body["passed"], body["total"]) == (1, 1)


def test_the_sandbox_still_applies_to_submitted_code() -> None:
    """`/execute` must not be a way around the isolation the escape tests verify —
    candidate code reaching the network through this path would bypass all of it."""
    body = _execute(
        "import socket\n"
        "def add(a, b):\n"
        "    try:\n"
        "        socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
        "        return 'REACHED'\n"
        "    except Exception:\n"
        "        return a + b\n"
    )
    assert body["outcome"] == "ok"
    assert body["passed"] == 3, "egress succeeded through /execute"
