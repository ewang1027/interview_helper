"""RFC 9457 `application/problem+json`, as docs/API.md specifies.

Every refusal the API makes says three things: what kind of problem it is (a stable
`type` URI a client can branch on), what happened in one line, and which request it
happened to. The alternative — FastAPI's default `{"detail": "..."}` — gives a client
nothing to branch on but prose, which is how error handling ends up matching on strings.

The `type` slugs are part of the contract. Renaming one is a breaking change.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

CONTENT_TYPE = "application/problem+json"
_BASE = "https://interview-helper.local/errors"


class ProblemError(Exception):
    """A refusal with a reason. Raised anywhere, rendered once, by the handler below.

    RFC 9457 calls this a *problem detail*; the `Error` suffix is the linter's naming
    rule for exceptions, not a second concept."""

    def __init__(
        self,
        *,
        status: int,
        slug: str,
        title: str,
        detail: str,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.extra = extra

    def body(self, instance: str) -> dict[str, Any]:
        return {
            "type": f"{_BASE}/{self.slug}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "instance": instance,
            **self.extra,
        }


def not_found(what: str, ident: str) -> ProblemError:
    return ProblemError(
        status=404,
        slug="not-found",
        title=f"Unknown {what}",
        detail=f"No {what} with id {ident!r}.",
    )


def wrong_state(detail: str, **extra: Any) -> ProblemError:
    """409 — the request is fine, the session is not in a state that allows it."""
    return ProblemError(
        status=409, slug="wrong-state", title="Wrong session state", detail=detail, **extra
    )


def unprocessable(detail: str, **extra: Any) -> ProblemError:
    """422 — well-formed, but invalid against the session's own plan or the corpus."""
    return ProblemError(
        status=422,
        slug="unprocessable",
        title="Request cannot be processed",
        detail=detail,
        **extra,
    )


def unavailable(detail: str) -> ProblemError:
    """503 — a dependency this request needs is not answering."""
    return ProblemError(
        status=503,
        slug="dependency-unavailable",
        title="A dependency is unavailable",
        detail=detail,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=exc.body(request.url.path),
            media_type=CONTENT_TYPE,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # docs/API.md maps a malformed body to 400 and a well-formed-but-invalid one to
        # 422. FastAPI cannot tell those apart — it raises the same error for both — so
        # this renders 400 ("malformed request") and the routes raise 422 themselves once
        # the body has parsed and the *meaning* turns out to be wrong.
        problem = ProblemError(
            status=400,
            slug="malformed-request",
            title="Malformed request",
            detail="The request body did not match the endpoint's schema.",
            errors=[{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
        )
        return JSONResponse(
            status_code=problem.status,
            content=problem.body(request.url.path),
            media_type=CONTENT_TYPE,
        )
