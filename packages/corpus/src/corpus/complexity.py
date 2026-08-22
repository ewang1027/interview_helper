"""What a `complexity_target` string means.

This lives in `corpus` rather than in the executor because it is a statement about the
**item contract**, not about running anything: the corpus decides which target strings are
sayable, so the corpus is where a string is mapped onto a band. The executor imports it to
judge a measurement; the validator imports it to refuse a target it could never judge.

One source of truth matters more here than usual. An unrecognised target does not fail —
it returns `None`, `judge` reports `inconclusive`, and `verify_reference_solutions
--complexity` only fails on a confident `slower_than_target`. So a typo silently disables
the check: measured, a quadratic solution declaring `O(n)` is caught at slope 2.07, and the
same solution declaring `O(n + m)` exits 0.
"""

from __future__ import annotations

import re


def classify_target(target: str | None) -> str | None:
    """Map a `complexity_target` string onto a measured band, or `None` if it is not one.

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
