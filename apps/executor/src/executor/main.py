"""Executor entrypoint.

Phase 0: health only. Phase 2 adds `POST /execute`, which is the point at which the
isolation tests in `apps/executor/tests` (marked `sandbox`) become load-bearing —
they must fail closed before any real execution path is merged.
"""

from __future__ import annotations

from fastapi import FastAPI

from executor import __version__

app = FastAPI(
    title="interview_helper executor",
    version=__version__,
    description="Runs untrusted candidate code under strict isolation.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
