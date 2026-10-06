"""FastAPI entrypoint.

Phase 3: the `/api/v1` router is mounted here, carrying sessions and the corpus routes,
and everything under that prefix requires a session cookie. `/health` and `/auth/*` stay
at the root — see `api.routes.__init__` for why the boundary is the prefix itself. The
interviewer agent and the SSE stream are not here yet.
"""

from __future__ import annotations

import re

from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from api import __version__
from api.auth import router as auth_router
from api.errors import install_error_handlers
from api.routes import api_v1

_EVENT_STREAM = re.compile(r"^/api/v1/sessions/[^/]+/events$")


class _GZipExceptEventStream:
    """Gzip every response except the session event stream, which is matched out by path.

    In production the ALB routes `/api` straight here and does not compress, so without
    this every JSON response went over the wire raw: `/api/v1/concepts` is ~81 KB, about
    20 KB compressed. Locally Caddy compresses, and passes through what arrives encoded.

    **Not `GZipMiddleware` alone.** It excludes `text/event-stream` from compression, but
    it still holds the response's header block until the first body chunk arrives, to
    decide how to rewrite the headers. The stream's first chunk can be the 15s ping, and
    `EventSource` does not fire `onopen` until headers land, so a live session would sit
    on "connecting" for fifteen seconds. This is the same failure the Caddyfile records,
    and the fix is the same: match the stream out by path, before anything wraps it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _EVENT_STREAM.match(scope["path"]):
            await self.app(scope, receive, send)
        else:
            await self.gzip(scope, receive, send)


app = FastAPI(
    title="interview_helper API",
    version=__version__,
    description="Adaptive mock-interview trainer for SWE and quant-trading loops.",
)

app.add_middleware(_GZipExceptEventStream)
install_error_handlers(app)
app.include_router(auth_router)
app.include_router(api_v1)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness. Deliberately does no I/O so it cannot fail for a downstream reason."""
    return {"status": "ok", "version": __version__}
