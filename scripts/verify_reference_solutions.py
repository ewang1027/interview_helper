"""Run every coding item's reference solution against its own tests, in the sandbox.

`docs/GRADING.md`: "Reference solutions are verified in CI, not trusted." This is that
check. It deliberately runs through `executor.sandbox`, the same isolation a candidate's
submission gets — verifying a solution in an environment more permissive than the one it
will actually be graded in proves the wrong thing.

Lives in `scripts/` rather than inside either package because it is the one place that
legitimately needs both: `corpus` (the items) and `executor` (the sandbox). Neither
package should take a dependency on the other to satisfy it — `apps/executor` in
particular is held to FastAPI/uvicorn/Pydantic by docs/SECURITY.md.

Usage: `uv run python scripts/verify_reference_solutions.py [--strict-stub-check]`
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from corpus.loader import load_items
from executor.sandbox import run_sandboxed

RESULT_MARKER = "##RESULT "

# Runs INSIDE the sandbox. Compares with == after a normalisation pass, because JSON
# round-trips tuples to lists and a solution returning a tuple is not wrong for that.
DRIVER = """
import json, sys

_PAYLOAD = json.loads({payload!r})

{solution}

def _norm(v):
    if isinstance(v, tuple):
        return [_norm(x) for x in v]
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {{k: _norm(x) for k, x in v.items()}}
    return v

_fn = globals().get(_PAYLOAD["entrypoint"])
if _fn is None:
    print("{marker}" + json.dumps({{
        "error": "entrypoint %r not defined by the solution" % _PAYLOAD["entrypoint"]}}))
    sys.exit(0)

_passed, _failures = 0, []
for _t in _PAYLOAD["tests"]:
    _name = _t.get("name") or "test"
    try:
        _got = _fn(*_t["input"])
    except Exception as exc:
        _failures.append({{"name": _name, "kind": _t.get("kind", "example"),
                          "message": "raised %s: %s" % (type(exc).__name__, exc)}})
        continue
    if _norm(_got) == _norm(_t["expected"]):
        _passed += 1
    else:
        _failures.append({{"name": _name, "kind": _t.get("kind", "example"),
                          "message": "expected %r, got %r" % (_t["expected"], _got)}})

print("{marker}" + json.dumps({{"passed": _passed,
                               "total": len(_PAYLOAD["tests"]),
                               "failures": _failures}}))
"""


def _run_one(solution: str, entrypoint: str, tests: list[dict[str, Any]]) -> dict[str, Any]:
    payload = json.dumps({"entrypoint": entrypoint, "tests": tests})
    program = DRIVER.format(payload=payload, solution=solution, marker=RESULT_MARKER)
    result = run_sandboxed(program)

    if result.outcome != "ok":
        return {"error": f"sandbox outcome {result.outcome}: {result.detail.strip()[:400]}"}
    for line in result.detail.splitlines():
        if line.startswith(RESULT_MARKER):
            parsed: dict[str, Any] = json.loads(line[len(RESULT_MARKER) :])
            return parsed
    return {"error": f"driver produced no result line: {result.detail.strip()[:400]}"}


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
        tests = grading.get("tests", [])
        if not entrypoint:
            print(f"FAIL {item.id}: grading.entrypoint is missing")
            failed = True
            continue

        for language, solution in (grading.get("reference_solutions") or {}).items():
            if language != "python":
                print(f"skip {item.id} [{language}]: only python is supported so far")
                continue

            outcome = _run_one(solution, entrypoint, tests)
            if "error" in outcome:
                print(f"FAIL {item.id} [{language}]: {outcome['error']}")
                failed = True
                continue

            passed, total = outcome["passed"], outcome["total"]
            if passed != total:
                print(f"FAIL {item.id} [{language}]: {passed}/{total}")
                for f in outcome["failures"]:
                    print(f"       {f['name']} ({f['kind']}): {f['message']}")
                failed = True
                continue
            print(f"ok   {item.id} [{language}]: {passed}/{total}")

            if args.strict_stub_check:
                stub = f"def {entrypoint}(*args, **kwargs):\n    return None\n"
                stub_outcome = _run_one(stub, entrypoint, tests)
                stub_passed = stub_outcome.get("passed", 0)
                if stub_passed:
                    print(
                        f"WEAK {item.id}: a do-nothing stub passes {stub_passed}/{total} "
                        "— those tests measure nothing"
                    )
                    failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
