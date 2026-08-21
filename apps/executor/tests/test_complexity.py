"""Target parsing, slope fitting, the verdict rule, and the driver's budget. Pure — no
Docker: the driver program is plain Python, so its budget arithmetic is exercised here by
running it in-process against a fake `time.process_time` the solution itself advances.

The end-to-end behaviour (does a quadratic submission actually get caught?) lives in
`test_complexity_probe_sandbox.py`, marked `sandbox`.
"""

from __future__ import annotations

import json
import math
import time

import pytest

from executor.complexity import (
    PROBE_MARKER,
    build_probe_program,
    classify_target,
    fit_slope,
    judge,
)


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


# --- The driver's budget -------------------------------------------------------------
#
# CI found the case these pin: the budget check between sizes cannot interrupt a run
# already in flight, so on a machine slow enough that one size alone exceeds the budget,
# the probe used to blow through its wall clock and report "timeout" — the most damning
# submission producing the least verdict. The driver now projects each size's cost from
# the growth it has already measured and stops *before* a size it cannot afford.

_GENERATOR = "def make_input(n):\n    return [n]\n"


def _solution_costing(seconds_per_n_squared: float) -> str:
    """A 'solution' whose runtime is exact: it advances the fake clock quadratically."""
    return (
        "def probe_me(n):\n"
        "    import time\n"
        f"    time._fake_clock[0] += {seconds_per_n_squared!r} * n * n\n"
    )


def _run_driver(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], solution: str
) -> dict:
    clock = [0.0]
    monkeypatch.setattr(time, "_fake_clock", clock, raising=False)
    monkeypatch.setattr(time, "process_time", lambda: clock[0])
    program = build_probe_program(
        _GENERATOR, solution, "probe_me", [1000, 2000, 4000, 8000], repeats=1
    )
    exec(program, {})
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith(PROBE_MARKER))
    payload: dict = json.loads(line[len(PROBE_MARKER) :])
    return payload


def test_the_driver_stops_before_a_size_the_budget_cannot_afford(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """At 2.5e-7·n² the sweep costs 0.25s, 1s, 4s, 16s: three sizes fit the 20s budget
    and the fourth, projected at 16s against 14.75s remaining, must never start. Three
    points are still a verdict — the impostor is caught, not timed out."""
    payload = _run_driver(monkeypatch, capsys, _solution_costing(2.5e-7))

    assert payload["truncated"] is True
    assert [n for n, _ in payload["points"]] == [1000, 2000, 4000]
    result = judge([(int(n), float(t)) for n, t in payload["points"]], "O(n)")
    assert result.verdict == "slower_than_target", result.detail


def test_the_driver_sweeps_every_size_it_can_afford(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _run_driver(monkeypatch, capsys, _solution_costing(1e-9))

    assert payload["truncated"] is False
    assert [n for n, _ in payload["points"]] == [1000, 2000, 4000, 8000]
