"""Target parsing, slope fitting and the verdict rule. Pure — no Docker.

The end-to-end behaviour (does a quadratic submission actually get caught?) lives in
`test_complexity_probe_sandbox.py`, marked `sandbox`.
"""

from __future__ import annotations

import math

from executor.complexity import classify_target, fit_slope, judge


def _curve(exponent: float, sizes=(1000, 2000, 4000, 8000), scale: float = 1e-6):
    """Synthetic timings on a clean n**exponent curve."""
    return [(n, scale * n**exponent) for n in sizes]


def test_classifies_the_targets_the_corpus_actually_uses() -> None:
    assert classify_target("O(n)") == "linear"
    assert classify_target("O(n log n)") == "linearithmic"
    assert classify_target("O(n^2)") == "quadratic"
    assert classify_target("O(1)") == "constant"
    assert classify_target("O(log n)") == "log"


def test_a_log_over_a_symbol_the_probe_cannot_vary_is_treated_as_constant() -> None:
    """`O(n log S)` over a fixed value range is linear in n. Judging it as linearithmic
    would hand a genuinely n-log-n submission a free pass, because the probe only ever
    grows n — it never grows S."""
    assert classify_target("O(n log S)") == "linear"
    assert classify_target("O(n log K)") == "linear"


def test_an_unparseable_target_yields_no_band_rather_than_a_guess() -> None:
    assert classify_target("O(fast enough)") is None
    assert classify_target(None) is None
    assert classify_target("") is None


def test_fits_known_exponents() -> None:
    assert math.isclose(fit_slope(_curve(1.0)), 1.0, abs_tol=1e-9)
    assert math.isclose(fit_slope(_curve(2.0)), 2.0, abs_tol=1e-9)


def test_fewer_than_three_points_is_not_enough_to_fit() -> None:
    assert fit_slope([(1000, 1e-3), (2000, 2e-3)]) is None


def test_a_linear_solution_matches_a_linear_target() -> None:
    assert judge(_curve(1.0), "O(n)").verdict == "matches"


def test_a_quadratic_solution_against_a_linear_target_is_caught() -> None:
    """The case docs/GRADING.md names: accepted-but-quadratic."""
    result = judge(_curve(2.0), "O(n)")
    assert result.verdict == "slower_than_target"
    assert result.penalises


def test_an_n_log_n_solution_is_not_failed_against_a_linear_target() -> None:
    """Measured `sorted` sits at ~1.5 against a linear band ceiling of 1.30. That is
    inside the margin deliberately: splitting O(n) from O(n log n) by timing is
    unreliable, and failing a correct submission writes false evidence of weakness."""
    result = judge(_curve(1.5), "O(n)")
    assert result.verdict == "inconclusive"
    assert not result.penalises


def test_samples_below_the_noise_floor_are_inconclusive() -> None:
    """A microsecond of work cannot support a complexity claim, however clean the fit."""
    tiny = [(n, 1e-9 * n) for n in (1000, 2000, 4000, 8000)]
    result = judge(tiny, "O(n)")
    assert result.verdict == "inconclusive"
    assert "noise floor" in result.detail


def test_an_unparseable_target_never_penalises() -> None:
    assert not judge(_curve(2.0), "O(fast enough)").penalises


def test_too_few_sizes_is_inconclusive_not_a_pass() -> None:
    result = judge([(1000, 1e-3), (2000, 2e-3)], "O(n)")
    assert result.verdict == "inconclusive"
    assert not result.penalises
