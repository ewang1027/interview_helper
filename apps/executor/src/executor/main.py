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
from executor.harness import build_driver, parse_result
from executor.protocol import ExecuteRequest, ExecuteResponse
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
