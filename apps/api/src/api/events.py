"""The live channel: what happened in a session, in order, as it happens.

docs/API.md specifies an SSE stream whose events carry a `type` and a **monotonic,
gap-free `seq`**, so a client that drops a connection can reconnect with `Last-Event-ID`
and know whether it missed anything. That gap-free promise is the whole design constraint —
it is why sequence numbers are assigned here, in one place, under a lock, rather than by
each publisher.

**In-process, and that is a real limitation.** The bus is a dictionary in memory. One
uvicorn process is what this runs on today, and under Fargate with two tasks a client could
hold its stream open against a task that is not running its turn — it would see nothing and
be told nothing was happening, which is worse than an error. `EventBus.publish` and
`.subscribe` are the seam where a shared broker (Postgres `LISTEN/NOTIFY`, or Redis) goes
when Phase 6 makes that real. It is written down rather than discovered.

**Subscribers poll a shared list rather than waiting on an asyncio queue.** Turns run in a
threadpool (a sync route) and the stream is async, so a queue means cross-thread event-loop
plumbing — `call_soon_threadsafe`, a loop reference captured at the right moment, and a
class of bug that shows up as a stream that silently stops. A 50 ms poll costs nothing next
to a model call and cannot deadlock. If the seam above is ever swapped for a real broker,
this goes with it.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# How much history a reconnecting client can be given. A turn writes a handful of events, a
# session a few dozen; 256 covers "the wifi dropped for a minute" and refuses to grow into
# a memory leak that only shows up on a long session.
BUFFER_SIZE = 256

# How often a subscriber looks for new events. Ten times faster than a human notices, and
# hundreds of times faster than a model answers.
POLL_SECONDS = 0.05


def sse_frame(event_type: str, **data: Any) -> dict[str, Any]:
    """One SSE frame, serialised the only way this system serialises them.

    A function rather than two call sites doing `json.dumps`: `sse_starlette` calls `str()`
    on whatever `data` it is handed, so a dict goes out as a Python repr that no JSON parser
    accepts — and that mistake is invisible until something tries to read the stream.
    """
    return {"event": event_type, "data": json.dumps({"type": event_type, **data}, default=str)}


@dataclass(frozen=True)
class Event:
    """One thing that happened. `seq` is assigned by the bus, never by the publisher."""

    seq: int
    type: str
    data: dict[str, Any]
    at: datetime

    def payload(self) -> dict[str, Any]:
        """What a client parses out of the `data:` line, minus the type `sse_frame` adds."""
        return {"seq": self.seq, "at": self.at.isoformat(), **self.data}

    def as_sse(self) -> dict[str, Any]:
        """The shape `sse_starlette` wants. `id` is what comes back as `Last-Event-ID`.

        `data` is serialised here rather than handed over as a dict: `sse_starlette` calls
        `str()` on whatever it is given, so a dict goes out as a Python repr — single
        quotes, `None` instead of `null` — which every JSON parser rejects. `default=str`
        because a stream that dies on one unserialisable field takes the whole session's
        channel with it.
        """
        return {"id": str(self.seq), **sse_frame(self.type, **self.payload())}


@dataclass
class _Channel:
    seq: int = 0
    events: deque[Event] = field(default_factory=lambda: deque(maxlen=BUFFER_SIZE))


class EventBus:
    """One channel per session. Thread-safe, in-process, bounded."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._channels: dict[str, _Channel] = {}

    def publish(self, session_id: str, event_type: str, **data: Any) -> Event:
        """Append an event and return it, with its sequence number."""
        with self._lock:
            channel = self._channels.setdefault(session_id, _Channel())
            channel.seq += 1
            event = Event(seq=channel.seq, type=event_type, data=data, at=datetime.now(UTC))
            channel.events.append(event)
            return event

    def since(self, session_id: str, after_seq: int) -> list[Event]:
        """Everything buffered after `after_seq`, oldest first."""
        with self._lock:
            channel = self._channels.get(session_id)
            if channel is None:
                return []
            return [event for event in channel.events if event.seq > after_seq]

    def latest_seq(self, session_id: str) -> int:
        with self._lock:
            channel = self._channels.get(session_id)
            return channel.seq if channel else 0

    def oldest_seq(self, session_id: str) -> int:
        """The lowest sequence still buffered, or 0 when nothing is.

        A client reconnecting from further back than this has missed events the server can
        no longer supply, and must be told so rather than handed a plausible-looking stream
        with a hole in it."""
        with self._lock:
            channel = self._channels.get(session_id)
            if channel is None or not channel.events:
                return 0
            return channel.events[0].seq

    def forget(self, session_id: str) -> None:
        """Drop a finished session's channel. Called when a session ends; a process that
        never forgets a session is a process that grows until it is restarted."""
        with self._lock:
            self._channels.pop(session_id, None)


_BUS = EventBus()


def bus() -> EventBus:
    """The process's bus. A function rather than the object so a test can override the
    dependency and a future broker can replace it without touching every call site."""
    return _BUS
