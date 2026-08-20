"""Turns (source, entrypoint, tests) into a self-contained program, and its output back
into an `ExecuteResponse`.

Split from `sandbox.py` because the two answer different questions: the sandbox decides
*how safely* something runs, this decides *what* runs and what the result means. It is
pure and importable without Docker, which is what lets the driver be unit-tested directly.

`scripts/verify_reference_solutions.py` uses this same module rather than its own copy —
a reference-solution check that built its driver differently from the one candidates are
graded by would be verifying the wrong thing.
"""

from __future__ import annotations

import json

from executor.protocol import ExecuteResponse, Outcome, TestCase, TestFailure

RESULT_MARKER = "##LEARN-RESULT "

# Runs INSIDE the sandbox, so it must be stdlib-only and must not assume the candidate's
# code is well-behaved: every call is wrapped, and the marker line is printed last so a
# candidate printing debug output cannot be mistaken for the result.
_DRIVER = """
import json, sys

_PAYLOAD = json.loads({payload!r})

{source}

def _norm(v):
    # JSON has no tuple, so a solution returning one is not wrong for that. Normalise
    # both sides rather than demanding the candidate match a serialisation detail.
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {{k: _norm(x) for k, x in v.items()}}
    return v

_fn = globals().get(_PAYLOAD["entrypoint"])
if not callable(_fn):
    print("{marker}" + json.dumps({{
        "error": "no callable named %r was defined" % _PAYLOAD["entrypoint"]}}))
    sys.exit(0)

_passed, _failures = 0, []
for _t in _PAYLOAD["tests"]:
    try:
        _got = _fn(*_t["input"])
    except Exception as exc:
        _failures.append({{"name": _t["name"], "kind": _t["kind"],
                          "message": "raised %s: %s" % (type(exc).__name__, exc)}})
        continue
    if _norm(_got) == _norm(_t["expected"]):
        _passed += 1
    else:
        _failures.append({{"name": _t["name"], "kind": _t["kind"],
                          "message": "expected %r, got %r" % (_t["expected"], _got)}})

print("{marker}" + json.dumps({{"passed": _passed,
                                "total": len(_PAYLOAD["tests"]),
                                "failures": _failures}}))

# Flush, then _exit rather than return: os._exit skips atexit handlers, so candidate
# code cannot register one that prints a second, later marker line after ours. Without
# this, "last marker wins" below would hand the run to whatever the candidate emitted
# on the way out.
sys.stdout.flush()
import os as _os
_os._exit(0)
"""


def build_driver(source: str, entrypoint: str, tests: tuple[TestCase, ...]) -> str:
    """A single self-contained program: the candidate's code plus a runner over `tests`."""
    payload = json.dumps(
        {
            "entrypoint": entrypoint,
            "tests": [
                {"input": list(t.input), "expected": t.expected, "name": t.name, "kind": t.kind}
                for t in tests
            ],
        }
    )
    return _DRIVER.format(payload=payload, source=source, marker=RESULT_MARKER)


def parse_result(raw: ExecuteResponse, total: int) -> ExecuteResponse:
    """Fold the driver's marker line into `raw`, which carries the sandbox's verdict.

    A non-`ok` sandbox outcome is returned untouched: a timeout or an OOM kill is a
    failed grading, and inventing a score for it is exactly what docs/GRADING.md forbids.
    """
    if raw.outcome != "ok":
        return raw.model_copy(update={"total": total})

    # The LAST marker line wins, not the first. The driver prints its line after every
    # test and then `os._exit`s, so anything a candidate emitted earlier — a stray print
    # that happens to match, or a deliberately forged line — is superseded rather than
    # believed. Taking the first match would let a candidate print a full score before
    # the real run even starts.
    #
    # Residual, stated plainly: a candidate that forges a marker and then exits the
    # process itself leaves its line as the only one. That is unclosable while the result
    # travels on the same stdout the candidate can write to, and it is out of scope by
    # docs/SECURITY.md's threat model — single user, no hostile population, and the only
    # person deceived is the one practising.
    for line in reversed(raw.detail.splitlines()):
        if not line.startswith(RESULT_MARKER):
            continue
        try:
            payload = json.loads(line[len(RESULT_MARKER) :])
        except json.JSONDecodeError:
            continue
        if "error" in payload:
            return raw.model_copy(
                update={"outcome": "harness_error", "total": total, "detail": payload["error"]}
            )
        return raw.model_copy(
            update={
                "passed": payload["passed"],
                "total": payload["total"],
                "failures": tuple(TestFailure(**f) for f in payload["failures"]),
            }
        )

    # Exit 0 with no marker line means the program ran but never reached the runner —
    # a candidate calling sys.exit(), or output truncated past the cap. Never read that
    # as "no failures".
    failed: Outcome = "harness_error"
    return raw.model_copy(
        update={
            "outcome": failed,
            "total": total,
            "detail": "the driver produced no result line; "
            f"last output: {raw.detail.strip()[-400:]}",
        }
    )
