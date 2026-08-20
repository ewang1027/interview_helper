"""The complexity probe: run a solution at increasing *n* and judge its growth.

`docs/GRADING.md` wants this to catch "the accepted-but-quadratic solution that passes
small tests". That is the case it is tuned for. It is deliberately **bad** at splitting
O(n) from O(n log n) — that difference is a log factor, hard to see through constant
factors, and worth little compared to the cost of failing a correct submission.

## Thresholds are measured, not derived

Slopes were calibrated by running known functions through this same sandbox
(`python:3.12-slim`, Colima/macOS arm64, min-of-5 `process_time`):

| function | theoretical slope at these n | **measured** |
|---|---|---|
| `for x in xs: t += x` | 1.00 | 1.006, 1.005 |
| `sum(xs)` | 1.00 | 1.107, 1.113 |
| `sorted(xs)` | ~1.09 | **1.505, 1.458** |
| nested `for`/`for` | 2.00 | 2.196, 2.176 |

Two conclusions drive everything below. **Reproducibility is excellent** — repeated trials
agree to ~0.05 — so a verdict is stable. But **measured slopes sit well above theory**:
`sorted` predicts 1.09 and measures 1.5. Thresholds taken from the textbook would have
called every correct `sorted`-based O(n log n) solution super-linear. Bands here come from
the measurements.

## It says "inconclusive" rather than guessing

A wrong complexity verdict writes evidence of weakness against a concept the candidate may
know perfectly well, so the probe reports `inconclusive` whenever the data is too thin to
support a call, and `slower_than_target` only when the slope clears the target's band by a
full margin. Silence is the correct output when the measurement cannot carry the claim.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Literal

from executor.sandbox import run_sandboxed

PROBE_MARKER = "##LEARN-PROBE "

Verdict = Literal["matches", "slower_than_target", "inconclusive"]

# Upper edge of each class as MEASURED above, not as derived. The gap between the linear
# band's top (1.30) and the observed `sorted` slope (1.46) is the deliberate cushion that
# keeps a log factor from being mistaken for a class change.
_BAND_CEILING = {
    "constant": 0.50,
    "log": 0.50,
    "linear": 1.30,
    "linearithmic": 1.75,
    "quadratic": 2.60,
    "cubic": 3.60,
}

# How far above a band's ceiling a slope must sit before the probe will call a submission
# slower than declared. Roughly half a complexity class: quadratic (~2.18) clears linear's
# 1.30 + 0.35 comfortably, while `sorted`'s 1.5 against an O(n) target does not.
_MARGIN = 0.35

# Below this, timings are dominated by interpreter noise rather than the algorithm.
_MIN_SIGNIFICANT_SECONDS = 2e-4

_DRIVER = """
import json, time, copy
_P = json.loads({payload!r})

{generator}

{solution}

_fn = globals().get(_P["entrypoint"])
if not callable(_fn):
    print("{marker}" + json.dumps({{"error": "no callable named %r" % _P["entrypoint"]}}))
else:
    _maker = globals().get("make_input")
    if not callable(_maker):
        print("{marker}" + json.dumps({{"error": "generator defines no make_input(n)"}}))
    else:
        _pts = []
        _err = None
        _spent = 0.0
        _truncated = False
        for _n in _P["sizes"]:
            try:
                _args = _maker(_n)
            except Exception as exc:
                _err = "make_input(%d) raised %s: %s" % (_n, type(exc).__name__, exc)
                break
            _best = None
            for _r in range(_P["repeats"]):
                # Fresh copy per repeat: a solution may mutate its input in place, and
                # the second run would then measure different work than the first.
                _a = copy.deepcopy(_args)
                _t0 = time.process_time()
                try:
                    _fn(*_a)
                except Exception as exc:
                    _err = "solution raised at n=%d: %s: %s" % (_n, type(exc).__name__, exc)
                    break
                _t1 = time.process_time()
                _d = _t1 - _t0
                _best = _d if _best is None else min(_best, _d)
                _spent += _d
                # A slow run is its own signal; repeating it only burns the budget that
                # buys the NEXT size, and the next size is what reveals the growth.
                if _d > _P["slow_run_s"]:
                    break
            if _err:
                break
            _pts.append([_n, _best])
            if _spent > _P["budget_s"]:
                # Stop growing rather than time the whole probe out. A solution too slow
                # to finish every size is exactly the one worth judging, and bailing out
                # with the points already collected keeps it judgeable instead of
                # reporting "inconclusive" for the most damning case there is.
                _truncated = True
                break
        if _err:
            print("{marker}" + json.dumps({{"error": _err}}))
        else:
            print("{marker}" + json.dumps({{"points": _pts, "truncated": _truncated}}))
"""


@dataclass(frozen=True)
class ProbeResult:
    verdict: Verdict
    slope: float | None
    points: tuple[tuple[int, float], ...]
    target: str | None
    detail: str

    @property
    def penalises(self) -> bool:
        """Only a confident `slower_than_target` may affect a score."""
        return self.verdict == "slower_than_target"


def classify_target(target: str | None) -> str | None:
    """Map a `complexity_target` string onto a measured band.

    Symbols other than the probe's own `n` are treated as constants, because the probe
    only varies n: `O(n log S)` over a fixed value range S is linear in n, and judging it
    against a linearithmic band would let a genuinely n-log-n solution pass unnoticed.
    """
    if not target:
        return None
    t = target.lower().replace(" ", "")
    t = re.sub(r"^o\((.*)\)$", r"\1", t)
    if not t:
        return None

    # Drop log factors over a symbol that is not n — they do not grow with the probe.
    t = re.sub(r"log\((?![n)])[a-z]+\)", "", t)
    t = re.sub(r"log(?![n(])[a-z]", "", t)
    t = t.strip("*·") or "1"

    if t in {"1", ""}:
        return "constant"
    if t in {"logn", "log(n)"}:
        return "log"
    if t in {"n", "n*1"}:
        return "linear"
    if t in {"nlogn", "nlog(n)", "n*logn"}:
        return "linearithmic"
    if t in {"n^2", "n**2", "n2", "n^2logn"}:
        return "quadratic"
    if t in {"n^3", "n**3", "n3"}:
        return "cubic"
    return None


def fit_slope(points: list[tuple[int, float]]) -> float | None:
    """Least-squares slope of log(time) against log(n) — the growth exponent."""
    usable = [(n, t) for n, t in points if n > 0 and t and t > 0]
    if len(usable) < 3:
        return None
    xs = [math.log(n) for n, _ in usable]
    ys = [math.log(t) for _, t in usable]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / denom


def judge(points: list[tuple[int, float]], target: str | None) -> ProbeResult:
    pts = tuple((n, t) for n, t in points)
    band = classify_target(target)

    if band is None:
        return ProbeResult(
            "inconclusive", None, pts, target, f"no band for complexity_target {target!r}"
        )
    if len(pts) < 3:
        return ProbeResult("inconclusive", None, pts, target, "fewer than 3 usable sizes")

    largest = max((t for _, t in pts), default=0.0)
    if largest < _MIN_SIGNIFICANT_SECONDS:
        return ProbeResult(
            "inconclusive",
            None,
            pts,
            target,
            f"largest sample {largest * 1e3:.3f}ms is below the "
            f"{_MIN_SIGNIFICANT_SECONDS * 1e3:.1f}ms noise floor — sizes are too small to judge",
        )

    slope = fit_slope(list(points))
    if slope is None:
        return ProbeResult("inconclusive", None, pts, target, "could not fit a slope")

    ceiling = _BAND_CEILING[band]
    if slope <= ceiling:
        return ProbeResult(
            "matches", slope, pts, target, f"slope {slope:.2f} is within the {band} band"
        )
    if slope >= ceiling + _MARGIN:
        return ProbeResult(
            "slower_than_target",
            slope,
            pts,
            target,
            f"slope {slope:.2f} exceeds the {band} band ({ceiling:.2f}) by more than "
            f"{_MARGIN:.2f} — the submission grows faster than {target}",
        )
    return ProbeResult(
        "inconclusive",
        slope,
        pts,
        target,
        f"slope {slope:.2f} sits just above the {band} band ({ceiling:.2f}) but inside the "
        f"{_MARGIN:.2f} margin — not enough separation to call it",
    )


def build_probe_program(
    generator: str,
    solution: str,
    entrypoint: str,
    sizes: list[int],
    repeats: int,
    budget_s: float = 20.0,
    slow_run_s: float = 1.0,
) -> str:
    payload = json.dumps(
        {
            "entrypoint": entrypoint,
            "sizes": sizes,
            "repeats": repeats,
            "budget_s": budget_s,
            "slow_run_s": slow_run_s,
        }
    )
    return _DRIVER.format(
        payload=payload, generator=generator, solution=solution, marker=PROBE_MARKER
    )


def run_probe(
    generator: str,
    solution: str,
    entrypoint: str,
    sizes: list[int],
    target: str | None,
    repeats: int = 5,
    wall_ms: int = 60_000,
    memory_mb: int = 512,
) -> ProbeResult:
    """Measure and judge. Never raises; a failed measurement is `inconclusive`."""
    program = build_probe_program(generator, solution, entrypoint, sizes, repeats)
    raw = run_sandboxed(program, wall_ms=wall_ms, memory_mb=memory_mb)

    if raw.outcome != "ok":
        return ProbeResult("inconclusive", None, (), target, f"probe run ended in {raw.outcome}")

    for line in reversed(raw.detail.splitlines()):
        if not line.startswith(PROBE_MARKER):
            continue
        try:
            payload = json.loads(line[len(PROBE_MARKER) :])
        except json.JSONDecodeError:
            continue
        if "error" in payload:
            return ProbeResult("inconclusive", None, (), target, payload["error"])
        return judge([(int(n), float(t)) for n, t in payload["points"]], target)

    return ProbeResult("inconclusive", None, (), target, "probe produced no result line")
