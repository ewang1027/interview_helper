"""The SSE route against a live Postgres.

Every test here drives a session to a finished state before reading the stream. That is not
squeamishness about hanging tests — it is the property the route promises: a stream on a
session that can produce no more events *ends*, rather than holding a connection open
forever. Testing it any other way would mean a timeout standing in for an assertion.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import sign_in
from fastapi.testclient import TestClient

from api.events import BUFFER_SIZE, bus
from api.main import app

pytestmark = pytest.mark.db


def finished_session(created_sessions: list[str]) -> tuple[TestClient, str]:
    """A session in `abandoned`, which is terminal, so its stream terminates."""
    client = sign_in(TestClient(app))
    created = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 45})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    created_sessions.append(session_id)
    assert client.post(f"/api/v1/sessions/{session_id}/end").status_code == 200
    return client, session_id


def read_stream(client: TestClient, url: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Every event the stream sends before it closes."""
    events: list[dict[str, Any]] = []
    with client.stream("GET", url, **kwargs) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line.removeprefix("data:").strip()))
    return events


def test_the_stream_replays_what_happened_and_then_ends(created_sessions):
    client, session_id = finished_session(created_sessions)
    bus().publish(session_id, "item.presented", item_id="i.code.0001", title="A problem")
    bus().publish(session_id, "agent.message.done", message_id="2", text="Hello.")

    events = read_stream(client, f"/api/v1/sessions/{session_id}/events")

    assert [event["type"] for event in events] == ["item.presented", "agent.message.done"]
    assert [event["seq"] for event in events] == [1, 2]
    assert events[1]["text"] == "Hello."
    bus().forget(session_id)


def test_last_event_id_replays_only_what_was_missed(created_sessions):
    """The header a browser resends on reconnect, without being asked to."""
    client, session_id = finished_session(created_sessions)
    for index in range(4):
        bus().publish(session_id, "tick", n=index)

    events = read_stream(
        client, f"/api/v1/sessions/{session_id}/events", headers={"Last-Event-ID": "2"}
    )
    assert [event["seq"] for event in events] == [3, 4]

    # `?after=` is the same thing for a client that would rather be explicit.
    explicit = read_stream(client, f"/api/v1/sessions/{session_id}/events?after=3")
    assert [event["seq"] for event in explicit] == [4]
    bus().forget(session_id)


def test_resuming_from_before_the_buffer_says_so(created_sessions):
    """A client that cannot tell it lost events is worse off than one handed an error."""
    client, session_id = finished_session(created_sessions)
    for _ in range(BUFFER_SIZE + 10):
        bus().publish(session_id, "tick")

    events = read_stream(
        client, f"/api/v1/sessions/{session_id}/events", headers={"Last-Event-ID": "1"}
    )
    assert events[0]["type"] == "stream.gap"
    assert events[0]["requested_after"] == 1
    assert events[0]["oldest_available"] == 11
    assert [event.get("seq") for event in events[1:]] == list(range(11, BUFFER_SIZE + 11))
    bus().forget(session_id)


def test_a_nonsense_resume_point_is_ignored_rather_than_fatal(created_sessions):
    client, session_id = finished_session(created_sessions)
    bus().publish(session_id, "tick")
    events = read_stream(
        client, f"/api/v1/sessions/{session_id}/events", headers={"Last-Event-ID": "not-a-number"}
    )
    assert [event["seq"] for event in events] == [1]
    bus().forget(session_id)


def test_the_stream_needs_a_session_cookie(created_sessions):
    _, session_id = finished_session(created_sessions)
    anonymous = TestClient(app)
    assert anonymous.get(f"/api/v1/sessions/{session_id}/events").status_code == 401


def test_another_users_stream_is_a_404_like_every_other_read(created_sessions):
    """A stream is a read and leaks the same thing, so it answers the same way."""
    _, session_id = finished_session(created_sessions)
    stranger = sign_in(TestClient(app), "01STRANGERSTRANGERSTRANG")
    assert stranger.get(f"/api/v1/sessions/{session_id}/events").status_code == 404
