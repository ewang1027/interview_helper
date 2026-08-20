"""`POST /probe` end to end, against real Docker. Marked `sandbox`.

`test_complexity.py` judges synthetic curves and `test_complexity_probe_sandbox.py`
measures real ones through `run_probe`. What is unproven without this file is the
*endpoint* — until it existed, the probe was reachable only from
`scripts/verify_reference_solutions.py`, so a candidate's submission had no path to the
one check that catches an accepted-but-quadratic answer.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from executor.main import app

pytestmark = pytest.mark.sandbox

client = TestClient(app)

# Ascending input: the worst case for a naive backward scan, free for a monotonic stack.
# A random generator would let the impostor below walk straight through — see
# docs/BUILDLOG.md, "a random generator disarms the probe entirely".
ASCENDING = "def make_input(n):\n    return [list(range(n))]\n"
SIZES = [2000, 4000, 8000, 16000]

LINEAR = (
    "def spans(readings):\n"
    "    out, stack = [], []\n"
    "    for i, v in enumerate(readings):\n"
    "        while stack and readings[stack[-1]] <= v:\n"
    "            stack.pop()\n"
    "        out.append(i - stack[-1] if stack else i + 1)\n"
    "        stack.append(i)\n"
    "    return out\n"
)

QUADRATIC = (
    "def spans(readings):\n"
    "    out = []\n"
    "    for i in range(len(readings)):\n"
    "        span, j = 1, i - 1\n"
    "        while j >= 0 and readings[j] <= readings[i]:\n"
    "            span += 1\n"
    "            j -= 1\n"
    "        out.append(span)\n"
    "    return out\n"
)


def _probe(source: str, **overrides: object) -> dict:
    body: dict = {
        "language": "python",
        "source": source,
        "entrypoint": "spans",
        "generator": ASCENDING,
        "sizes": SIZES,
        "target": "O(n)",
        "repeats": 3,
    }
    body.update(overrides)
    resp = client.post("/probe", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_linear_solution_matches_over_http() -> None:
    body = _probe(LINEAR)
    assert body["verdict"] == "matches", body["detail"]
    assert len(body["points"]) == len(SIZES)


def test_a_quadratic_solution_is_caught_over_http() -> None:
    """The case the probe exists for, now reachable by the grader rather than only by CI."""
    body = _probe(QUADRATIC)
    assert body["verdict"] == "slower_than_target", body["detail"]
    assert body["slope"] > 1.65


def test_a_solution_that_raises_is_inconclusive_not_slow() -> None:
    """A submission the generator's input breaks measures nothing. Reporting that as
    `slower_than_target` would write evidence of the wrong weakness."""
    body = _probe("def spans(readings):\n    raise ValueError('nope')\n")
    assert body["verdict"] == "inconclusive"
    assert "raised" in body["detail"]
