"""The complexity probe end to end, against real Docker. Marked `sandbox`.

The unit tests judge synthetic curves; these prove the measurement itself works — that a
real quadratic solution measured through a real container is actually caught, and a real
linear one is not.
"""

from __future__ import annotations

import pytest

from executor.complexity import run_probe

pytestmark = pytest.mark.sandbox

# Ascending input: the worst case for a naive backward scan, free for a monotonic stack.
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


def test_a_linear_solution_matches_its_linear_target() -> None:
    result = run_probe(ASCENDING, LINEAR, "spans", SIZES, "O(n)")
    assert result.verdict == "matches", result.detail
    assert result.slope is not None and result.slope < 1.3


def test_a_quadratic_solution_is_caught() -> None:
    """The whole point of the probe. Measured slope lands near 2.0."""
    result = run_probe(ASCENDING, QUADRATIC, "spans", SIZES, "O(n)")
    assert result.verdict == "slower_than_target", result.detail
    assert result.penalises
    assert result.slope is not None and result.slope > 1.65


def test_a_random_generator_hides_the_very_defect_the_probe_exists_for() -> None:
    """Pinning a finding rather than an intention.

    On random input the naive scan terminates almost immediately, so it genuinely is
    near-linear and the probe correctly declines to fail it. The probe is therefore only
    as adversarial as its generator — which is why the corpus generators are worst-case
    by construction, and why this test exists to stop someone "simplifying" one back to
    `random.randrange` and quietly disarming the check.
    """
    random_gen = (
        "def make_input(n):\n"
        "    import random\n"
        "    r = random.Random(20260820)\n"
        "    return [[r.randrange(1000) for _ in range(n)]]\n"
    )
    result = run_probe(random_gen, QUADRATIC, "spans", SIZES, "O(n)")
    assert not result.penalises, (
        "a random generator unexpectedly caught the quadratic — if this now fails, the "
        "finding it records has changed and the corpus generators should be revisited"
    )


def test_a_probe_that_cannot_run_is_inconclusive_not_a_penalty() -> None:
    """A broken generator must never be scored against the candidate."""
    result = run_probe(
        "def make_input(n):\n    raise ValueError('boom')\n", LINEAR, "spans", SIZES, "O(n)"
    )
    assert result.verdict == "inconclusive"
    assert not result.penalises
    assert "boom" in result.detail


def test_a_missing_entrypoint_is_inconclusive_not_a_penalty() -> None:
    result = run_probe(ASCENDING, LINEAR, "not_defined", SIZES, "O(n)")
    assert result.verdict == "inconclusive"
    assert not result.penalises
