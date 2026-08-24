"""`Idempotency-Key`, as docs/API.md specifies it.

The problem it solves is narrow and real: a browser on a flaky network retries, and
`POST /sessions` retried twice used to create two sessions. docs/API.md has listed this
as owed since Phase 3 and specifically as owed *before* the web app; the web app arrived
first, sending the header at a server that dropped it.

**The database decides, not a read-then-write.** Two concurrent retries of one request
both find no row and both proceed unless the insert itself refuses the second. That is
the same failure the unique constraints on `artifacts` and `turns` exist for, and this
uses the same mechanism rather than a lock or a check.

Three answers, one per state the key can be in:

- **new** — the row is inserted with no response, the handler runs, the response is
  stored. That row is the reservation.
- **replayed** — a row with the same fingerprint and a stored response. The stored
  response is returned and the handler never runs, which is what stops a second session
  being created or a second grading being queued.
- **in flight** — a row with the same fingerprint and no response yet. `409`, because the
  honest answer to "did my first request work?" while it is still running is "ask again",
  not a second execution and not an empty body.

A key reused with a *different* body is `422`. Returning the first request's answer to a
different question would be silently wrong, which is worse than refusing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from api.errors import ProblemError
from api.models import IdempotencyKey

# Long enough for a UUID and then some; short enough that the column is not a place to
# put a payload. A client that needs more than this is doing something else.
MAX_KEY_LENGTH = 255


def fingerprint(body: Any) -> str:
    """A stable hash of the request body.

    `default=str` for the same reason the SSE frame uses it — a body carrying something
    unserialisable must not turn a retry into a 500 — and `sort_keys` because two
    equivalent bodies that differ only in key order are the same request.
    """
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _reused(endpoint: str) -> ProblemError:
    return ProblemError(
        status=422,
        slug="idempotency-key-reused",
        title="Idempotency key reused with a different request",
        detail=(
            f"This Idempotency-Key has already been used on {endpoint} with a different "
            "body. Use a new key for a new request."
        ),
    )


def _in_flight(endpoint: str) -> ProblemError:
    return ProblemError(
        status=409,
        slug="idempotency-key-in-flight",
        title="The original request is still running",
        detail=(
            f"A request to {endpoint} with this Idempotency-Key has not finished yet. "
            "Retry once it has; it will replay the original response."
        ),
    )


def run_once(
    db: Session,
    *,
    user_id: str,
    endpoint: str,
    key: str | None,
    body: Any,
    handler: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Run `handler`, or replay what it returned the first time this key was seen.

    With no key, the handler simply runs — the header is optional, and requiring it would
    break every client that predates it.
    """
    if key is None:
        return handler()

    key = key.strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        raise ProblemError(
            status=400,
            slug="idempotency-key-invalid",
            title="Malformed Idempotency-Key",
            detail=f"An Idempotency-Key must be 1 to {MAX_KEY_LENGTH} characters.",
        )

    digest = fingerprint(body)
    row = IdempotencyKey(user_id=user_id, endpoint=endpoint, key=key, request_fingerprint=digest)
    db.add(row)
    try:
        # Committed on its own, before the handler runs. The reservation has to be
        # durable and visible to a concurrent retry *while* the first request is still
        # working — held in an open transaction it would be neither.
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(IdempotencyKey, (user_id, endpoint, key))
        if existing is None:
            # The row lost the insert race and then vanished before it could be read.
            # Nothing sensible can be replayed, and guessing is worse than saying so.
            raise _in_flight(endpoint) from None
        if existing.request_fingerprint != digest:
            raise _reused(endpoint) from None
        if existing.response_json is None:
            raise _in_flight(endpoint) from None
        replayed: dict[str, Any] = json.loads(existing.response_json)
        return replayed

    try:
        result = handler()
    except Exception:
        # A failed request must not be replayable: the caller is expected to retry it, and
        # a reservation left behind would answer that retry with a 409 forever.
        db.delete(db.get(IdempotencyKey, (user_id, endpoint, key)))
        db.commit()
        raise

    stored = db.get(IdempotencyKey, (user_id, endpoint, key))
    if stored is not None:
        stored.response_json = json.dumps(result, default=str)
        db.add(stored)
        db.commit()
    return result
