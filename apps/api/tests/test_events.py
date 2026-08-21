"""The event bus: sequence numbers, the buffer, and what a reconnecting client is owed."""

from __future__ import annotations

import json
import threading

from api.events import BUFFER_SIZE, EventBus


def test_sequence_numbers_are_monotonic_and_gap_free():
    """The whole promise of the stream. A client can only tell loss from silence if the
    numbers it sees have no holes that are not real ones."""
    bus = EventBus()
    seqs = [bus.publish("s1", "tick", n=i).seq for i in range(10)]
    assert seqs == list(range(1, 11))


def test_sessions_do_not_share_a_sequence():
    bus = EventBus()
    bus.publish("s1", "tick")
    bus.publish("s1", "tick")
    assert bus.publish("s2", "tick").seq == 1


def test_concurrent_publishers_never_reuse_a_number():
    """Turns run in a threadpool and grading runs in a background task, so two publishers
    to one session genuinely overlap. A duplicated `seq` would make a client believe it had
    already seen an event it never got."""
    bus = EventBus()
    barrier = threading.Barrier(8)

    def publish() -> None:
        barrier.wait()
        for _ in range(25):
            bus.publish("s1", "tick")

    threads = [threading.Thread(target=publish) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert bus.latest_seq("s1") == 200
    buffered = bus.since("s1", 0)
    assert len(buffered) == min(200, BUFFER_SIZE)
    assert [event.seq for event in buffered] == sorted(event.seq for event in buffered)
    assert len({event.seq for event in buffered}) == len(buffered)


def test_since_returns_only_what_the_client_has_not_seen():
    bus = EventBus()
    for index in range(5):
        bus.publish("s1", "tick", n=index)
    assert [event.data["n"] for event in bus.since("s1", 3)] == [3, 4]
    assert bus.since("s1", 5) == []
    assert bus.since("unknown-session", 0) == []


def test_the_buffer_is_bounded_and_says_where_it_starts():
    """A reconnecting client that asks for something older than this has really lost
    events, and the route turns that into a `stream.gap` rather than a quiet hole."""
    bus = EventBus()
    for _ in range(BUFFER_SIZE + 20):
        bus.publish("s1", "tick")
    assert bus.latest_seq("s1") == BUFFER_SIZE + 20
    assert bus.oldest_seq("s1") == 21
    assert len(bus.since("s1", 0)) == BUFFER_SIZE


def test_an_empty_channel_reports_no_oldest():
    bus = EventBus()
    assert bus.oldest_seq("s1") == 0
    assert bus.latest_seq("s1") == 0


def test_forgetting_a_session_releases_it():
    """A process that never forgets a session grows until it is restarted."""
    bus = EventBus()
    bus.publish("s1", "tick")
    bus.forget("s1")
    assert bus.latest_seq("s1") == 0
    assert bus.since("s1", 0) == []


def test_an_event_renders_with_its_id_and_type():
    bus = EventBus()
    event = bus.publish("s1", "hint.revealed", level=2, score_penalty=0.1)
    rendered = event.as_sse()
    assert rendered["id"] == "1"
    assert rendered["event"] == "hint.revealed"

    # A string, not a dict: `sse_starlette` calls `str()` on what it is given, so a dict
    # would go out as a Python repr and no JSON parser would take it.
    assert isinstance(rendered["data"], str)
    payload = json.loads(rendered["data"])
    assert payload["type"] == "hint.revealed"
    assert payload["seq"] == 1
    assert payload["level"] == 2
    assert payload["at"].endswith("+00:00")


def test_an_unserialisable_field_does_not_kill_the_stream():
    """One bad value must not take the session's whole channel down with it."""
    bus = EventBus()
    event = bus.publish("s1", "tool.result", output={"when": object()})
    assert json.loads(event.as_sse()["data"])["output"]["when"].startswith("<object")
