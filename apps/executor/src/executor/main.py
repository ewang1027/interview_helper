"""Executor entrypoint.

Phase 2: `/execute` runs a candidate's code against an item's tests inside the sandbox.
The isolation tests in `apps/executor/tests` (marked `sandbox`) are load-bearing from
here on — they landed with this endpoint, not after it.

This service holds **no** database, model, or AWS credentials, and never evaluates
candidate code in its own process: the code runs in a throwaway container and this
process only launches it and reads the result. See docs/ARCHITECTURE.md, "Where the
sandbox actually lives", for why that stays true under Fargate, where the task itself
becomes the boundary and there is no socket at all.
"""

from __future__ import annotations

from fastapi import FastAPI

from executor import __version__
from executor.complexity import run_probe
from executor.harness import build_driver, parse_result
from executor.protocol import ExecuteRequest, ExecuteResponse, ProbeRequest, ProbeResponse
from executor.sandbox import run_sandboxed

app = FastAPI(
    title="interview_helper executor",
    version=__version__,
    description="Runs untrusted candidate code under strict isolation.",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness. Deliberately does no I/O so it cannot fail for a downstream reason."""
    return {"status": "ok", "version": __version__}


@app.post("/execute")
def execute(request: ExecuteRequest) -> ExecuteResponse:
    """Run `request.source` against the selected tests.

    Always returns 200 with an outcome — a crashed, timed-out or OOM-killed run is a
    *result*, not an HTTP error, because the caller has to record it as a failed grading
    either way and an exception here would lose the detail.
    """
    if request.language != "python":
        return ExecuteResponse(
            outcome="harness_error",
            detail=f"language {request.language!r} is not supported yet",
        )

    tests = request.selected()
    if not tests:
        return ExecuteResponse(
            outcome="harness_error",
            detail="test_selection matched none of the item's tests",
        )

    program = build_driver(request.source, request.entrypoint, tests)
    raw = run_sandboxed(program, wall_ms=request.wall_ms, memory_mb=request.memory_mb)
    return parse_result(raw, total=len(tests))


@app.post("/probe")
def probe(request: ProbeRequest) -> ProbeResponse:
    """Measure how `request.source` grows with n, and judge it against `target`.

    Like `/execute`, always 200. A measurement that could not be made is `inconclusive`,
    which is a verdict the caller records — the probe exists to catch a slow-but-correct
    solution, and a probe that errored has caught nothing, not proved something.

    Until this existed the probe was reachable only from
    `scripts/verify_reference_solutions.py`, so the one grader that could run it was CI.
    A candidate's submission had no path to it at all.
    """
    if request.language != "python":
        return ProbeResponse(
            verdict="inconclusive",
            target=request.target,
            detail=f"language {request.language!r} is not supported yet",
        )

    result = run_probe(
        request.generator,
        request.source,
        request.entrypoint,
        list(request.sizes),
        request.target,
        repeats=request.repeats,
        wall_ms=request.wall_ms,
        memory_mb=request.memory_mb,
    )
    return ProbeResponse(
        verdict=result.verdict,
        slope=result.slope,
        points=result.points,
        target=result.target,
        detail=result.detail,
    )
