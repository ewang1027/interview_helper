"""`GET /sessions/{id}/events` — the SSE stream docs/API.md specifies.

Three promises this route has to keep, and each one shapes the code:

- **`seq` is monotonic and gap-free**, so a client can tell loss from silence. The bus
  assigns it; this route never renumbers.
- **Reconnect with `Last-Event-ID`** replays what the client missed. When the requested
  point has fallen out of the buffer, the client is *told* — a `stream.gap` event — rather
  than handed a plausible stream with a hole in it. A client that cannot tell it lost
  events is worse off than one that gets an error.
- **The connection is kept alive.** An idle model call can take twenty seconds and proxies
  close quiet connections; `sse_starlette`'s `ping` sends a comment frame meanwhile.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query
from sqlmodel import Session
from sse_starlette.sse import EventSourceResponse

from api import sessions as service
from api.auth import CurrentPrincipal
from api.db import get_engine, get_session
from api.events import POLL_SECONDS, EventBus, bus, sse_frame
from api.models import InterviewSession

router = APIRouter(tags=["sessions"])

# `scope="function"`: closed when the handler returns, not when the response finishes. The
# default `yield` teardown runs after a streamed response completes, so the connection the
# ownership check used stayed checked out, idle in a transaction, for the whole stream — up
# to `MAX_STREAM_SECONDS`, against a pool of 5 + 10 overflow.
DbSession = Annotated[Session, Depends(get_session, scope="function")]
Bus = Annotated[EventBus, Depends(bus)]

# Long enough that a slow turn does not look like a hang, short enough that a forgotten tab
# does not hold a connection forever.
PING_SECONDS = 15

# How long one stream may stay open. SSE clients reconnect by themselves and `Last-Event-ID`
# makes that lossless, so a bounded stream costs a client nothing — while an unbounded one
# costs a pooled database connection per abandoned tab.
MAX_STREAM_SECONDS = 30 * 60

# How often the stream re-reads the session's status as a backstop. The terminal
# `session.state` event is what ends a stream; this catches the transition the bus cannot
# show — a channel evicted or forgotten, or a write from outside this process. It was every
# `POLL_SECONDS`, 20 queries a second per open stream, each blocking the event loop.
FINISHED_CHECK_SECONDS = 2.0


def _resume_from(last_event_id: str | None, after: int | None) -> int:
    """Where to replay from. `Last-Event-ID` is the header a browser resends automatically;
    `?after=` is the same thing for a client that would rather be explicit."""
    for candidate in (last_event_id, after):
        if candidate is None:
            continue
        try:
            return max(0, int(candidate))
        except (TypeError, ValueError):
            continue
    return 0


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    db: DbSession,
    principal: CurrentPrincipal,
    channel: Bus,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
) -> EventSourceResponse:
    """Stream this session's events until the client goes away.

    Ownership is checked before the stream opens, with the same 404 every other session
    route gives for somebody else's id — a stream is a read, and it leaks the same thing.
    """
    row = service.get_session(db, session_id, user_id=principal.user_id)
    finished_at_open = row.status in service.REPORTABLE_STATES
    resume = _resume_from(last_event_id, after)

    def _is_finished(sid: str) -> bool:
        with Session(get_engine()) as fresh:
            row = fresh.get(InterviewSession, sid)
            return row is None or row.status in service.REPORTABLE_STATES

    async def publish() -> AsyncIterator[dict[str, Any]]:
        cursor = resume
        oldest = channel.oldest_seq(session_id)
        if resume and oldest and resume < oldest - 1:
            # The client asked to resume from before the buffer starts. Say so, and say
            # what it can still be given, so it can refetch state rather than assume it is
            # up to date.
            yield sse_frame(
                "stream.gap",
                requested_after=resume,
                oldest_available=oldest,
                detail="Events between those points are gone; refetch the session.",
            )
            cursor = oldest - 1

        started = last_check = time.monotonic()
        finished = finished_at_open
        while True:
            for event in channel.since(session_id, cursor):
                cursor = event.seq
                yield event.as_sse()
                if event.type == "session.state" and event.data.get("state") in (
                    service.REPORTABLE_STATES
                ):
                    finished = True
            # Re-read the status rather than testing the row loaded before the stream
            # opened. That row is a *snapshot*: a stream opened while the session was
            # briefing tested `briefing` forever, so ending the session while a client was
            # attached left the generator neither yielding nor stopping. Measured: four
            # seconds after the session became `abandoned`, still hanging. It matters more
            # than a stuck tab, because `DbSession` is a `yield` dependency that FastAPI
            # releases only when the response completes — so each hung stream pins a
            # pooled connection, and the default pool is 5 + 10 overflow. Fifteen
            # abandoned tabs stall every request the API has.
            #
            # A short-lived session of its own, not `db`: that one belongs to the request
            # and holding a transaction open across the whole stream is the same bug in a
            # different coat.
            #
            # **2026-10-05:** the re-read is now the backstop, not the signal. Both terminal
            # transitions publish `session.state` after they commit, and the loop above
            # catches that. The database is asked every `FINISHED_CHECK_SECONDS`, in a
            # thread, so a sync query no longer stalls the event loop 20 times a second.
            now = time.monotonic()
            if not finished and now - last_check >= FINISHED_CHECK_SECONDS:
                last_check = now
                finished = await asyncio.to_thread(_is_finished, session_id)
            if finished and not channel.since(session_id, cursor):
                # Nothing more will happen on a finished session, so the stream ends rather
                # than holding a connection open for events that cannot arrive.
                break
            if time.monotonic() - started > MAX_STREAM_SECONDS:
                # A backstop for the case the check above cannot see: a session that is
                # never finished and never abandoned, whose client has gone away without
                # the socket noticing. SSE clients reconnect on their own, and
                # `Last-Event-ID` makes that lossless.
                yield sse_frame(
                    "stream.timeout",
                    after=cursor,
                    detail="Reconnect with Last-Event-ID to continue.",
                )
                break
            await asyncio.sleep(POLL_SECONDS)

    return EventSourceResponse(publish(), ping=PING_SECONDS)
