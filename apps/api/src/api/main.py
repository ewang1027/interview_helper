"""FastAPI entrypoint.

Phase 3: the `/api/v1` router is mounted here, carrying sessions and the corpus routes,
and everything under that prefix requires a session cookie. `/health` and `/auth/*` stay
at the root — see `api.routes.__init__` for why the boundary is the prefix itself. The
interviewer agent and the SSE stream are not here yet; docs/BUILDLOG.md is authoritative
about what that means.
"""

from __future__ import annotations

from fastapi import FastAPI

from api import __version__
from api.auth import router as auth_router
from api.errors import install_error_handlers
from api.routes import api_v1

app = FastAPI(
    title="interview_helper API",
    version=__version__,
    description="Adaptive mock-interview trainer for SWE and quant-trading loops.",
)

install_error_handlers(app)
app.include_router(auth_router)
app.include_router(api_v1)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness. Deliberately does no I/O so it cannot fail for a downstream reason."""
    return {"status": "ok", "version": __version__}
