"""Run every coding item's reference solution against its own tests, in the sandbox.

`docs/GRADING.md`: "Reference solutions are verified in CI, not trusted." This is that
check. It goes through `executor.harness` + `executor.sandbox` — the *same* driver and
the *same* isolation a candidate's submission gets. It used to carry its own copy of the
driver, which meant it could have verified a solution against a grader subtly unlike the
real one; sharing the module removes that whole class of drift.

Lives in `scripts/` because it is the one place that legitimately needs both `corpus`
(the items) and `executor` (the sandbox). Neither package should depend on the other —
`apps/executor` in particular is held to FastAPI/uvicorn/Pydantic by docs/SECURITY.md.

Usage: `uv run python scripts/verify_reference_solutions.py [--strict-stub-check]`
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from corpus.loader import load_items
from executor.complexity import run_probe
from executor.harness import build_driver, parse_result
from executor.protocol import ExecuteResponse, TestCase
from executor.sandbox import run_sandboxed


def _cases(tests: list[dict[str, Any]]) -> tuple[TestCase, ...]:
    return tuple(
        TestCase(
            input=tuple(t.get("input", [])),
            expected=t.get("expected"),
            name=t.get("name") or f"test_{i}",
            kind=t.get("kind", "edge"),
            hidden=t.get("hidden", True),
        )
        for i, t in enumerate(tests)
    )


def _run(solution: str, entrypoint: str, cases: tuple[TestCase, ...]) -> ExecuteResponse:
    program = build_driver(solution, entrypoint, cases)
    return parse_result(run_sandboxed(program), total=len(cases))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict-stub-check",
        action="store_true",
        help=(
            "Also assert a do-nothing stub FAILS each item. A test suite a stub can pass "
            "measures nothing — see docs/BUILDLOG.md on weak tests."
        ),
    )
    parser.add_argument(
        "--complexity",
        action="store_true",
        help=(
            "Also run the complexity probe against each reference solution and fail if it "
            "is measurably slower than the item's own declared complexity_target. Slow: "
            "each item runs at four sizes."
        ),
    )
    args = parser.parse_args()

    items = [
        i
        for i in load_items()
        if i.grading and i.grading.get("type") == "tests" and i.kind == "instance"
    ]
    if not items:
        print("no coding items with a tests contract yet — nothing to verify")
        return 0

    failed = False
    for item in items:
        grading = item.grading or {}
        entrypoint = grading.get("entrypoint")
        cases = _cases(grading.get("tests", []))
        if not entrypoint:
            print(f"FAIL {item.id}: grading.entrypoint is missing")
            failed = True
            continue

        for language, solution in (grading.get("reference_solutions") or {}).items():
            if language != "python":
                print(f"skip {item.id} [{language}]: only python is supported so far")
                continue

            result = _run(solution, entrypoint, cases)
            if not result.is_gradeable:
                print(f"FAIL {item.id} [{language}]: {result.outcome} — {result.detail[:300]}")
                failed = True
                continue
            if result.passed != result.total:
                print(f"FAIL {item.id} [{language}]: {result.passed}/{result.total}")
                for f in result.failures:
                    print(f"       {f.name} ({f.kind}): {f.message}")
                failed = True
                continue
            print(f"ok   {item.id} [{language}]: {result.passed}/{result.total}")

            if args.strict_stub_check:
                stub = f"def {entrypoint}(*args, **kwargs):\n    return None\n"
                stub_result = _run(stub, entrypoint, cases)
                if stub_result.is_gradeable and stub_result.passed:
                    print(
                        f"WEAK {item.id}: a do-nothing stub passes "
                        f"{stub_result.passed}/{stub_result.total} — those tests measure nothing"
                    )
                    failed = True

            if args.complexity:
                probe_spec = grading.get("complexity_probe")
                target = grading.get("complexity_target")
                if not probe_spec:
                    if target:
                        # complexity_target without a probe is a claim nothing checks.
                        print(f"     {item.id}: declares {target} but ships no complexity_probe")
                    continue
                probe = run_probe(
                    probe_spec["generator"],
                    solution,
                    entrypoint,
                    probe_spec["sizes"],
                    target,
                    repeats=probe_spec.get("repeats", 5),
                )
                slope = f"{probe.slope:.2f}" if probe.slope is not None else "n/a"
                if probe.penalises:
                    print(f"SLOW {item.id}: slope {slope} vs {target} — {probe.detail}")
                    failed = True
                else:
                    print(f"     {item.id}: complexity {probe.verdict} (slope {slope} vs {target})")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
