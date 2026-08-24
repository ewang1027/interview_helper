"""`Idempotency-Key` on the two routes docs/API.md specifies it for.

The property under test is not "the header is accepted" — it is that the *effect* happens
once. A replay that returns the right body while creating a second session, or queueing a
second grading, would pass a shallower test and be the bug this exists to prevent. So
every case counts rows.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from conftest import sign_in
from fastapi.testclient import TestClient
from sqlmodel import Session, col, func, select

from api.db import get_engine
from api.main import app
from api.models import Artifact, IdempotencyKey, InterviewSession

pytestmark = pytest.mark.db

NEW_SESSION = {"mode": "coding", "budget_minutes": 45}


def session_count(user_id: str) -> int:
    with Session(get_engine()) as db:
        return int(
            db.exec(
                select(func.count())
                .select_from(InterviewSession)
                .where(col(InterviewSession.user_id) == user_id)
            ).one()
        )


def create(client: TestClient, key: str | None = None, **body: Any):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/api/v1/sessions", json={**NEW_SESSION, **body}, headers=headers)


def test_the_same_key_twice_creates_one_session(created_sessions, user_id):
    """The case docs/API.md named: a retry on a flaky network made two sessions."""
    client = sign_in(TestClient(app))
    before = session_count(user_id)

    first = create(client, "retry-me")
    assert first.status_code == 201, first.text
    created_sessions.append(first.json()["id"])

    second = create(client, "retry-me")
    assert second.status_code == 201, second.text

    # Same answer, and — the part that matters — one session, not two.
    assert second.json() == first.json()
    assert session_count(user_id) == before + 1


def test_without_a_key_a_retry_still_creates_two(created_sessions, user_id):
    """The header is optional, and its absence must not be silently treated as present.

    This is the behaviour the feature *permits*, asserted so that making the header
    mandatory — or defaulting it — is a deliberate change rather than an accident.
    """
    client = sign_in(TestClient(app))
    before = session_count(user_id)

    for _ in range(2):
        response = create(client)
        assert response.status_code == 201
        created_sessions.append(response.json()["id"])

    assert session_count(user_id) == before + 2


def test_a_key_reused_with_a_different_body_is_refused(created_sessions):
    """Replaying the first answer to a different question would be silently wrong."""
    client = sign_in(TestClient(app))
    first = create(client, "same-key", budget_minutes=45)
    assert first.status_code == 201
    created_sessions.append(first.json()["id"])

    clash = create(client, "same-key", budget_minutes=90)
    assert clash.status_code == 422
    assert clash.json()["type"].endswith("/idempotency-key-reused")


def test_one_key_on_two_routes_is_two_keys(created_sessions):
    """Scoped by endpoint: a client reusing one key per logical operation is normal."""
    client = sign_in(TestClient(app))
    created = create(client, "shared")
    assert created.status_code == 201
    session_id = created.json()["id"]
    created_sessions.append(session_id)

    item_id = created.json()["plan"]["items"][0]["item_id"]
    submitted = client.post(
        f"/api/v1/sessions/{session_id}/submissions",
        json={"item_id": item_id, "kind": "code", "language": "python", "content": "x = 1"},
        headers={"Idempotency-Key": "shared"},
    )
    # Not a 422 for a reused key — the endpoint is part of the identity.
    assert submitted.status_code == 202, submitted.text


def test_a_replayed_submission_queues_one_grading(created_sessions):
    """The one-per-item 409 already stopped two artifacts. It could not stop a retry
    being told its submission had failed when it had not — and a second grading is a
    second set of immutable evidence rows, which no replay can take back."""
    client = sign_in(TestClient(app))
    created = create(client)
    session_id = created.json()["id"]
    created_sessions.append(session_id)
    item_id = created.json()["plan"]["items"][0]["item_id"]
    body = {"item_id": item_id, "kind": "code", "language": "python", "content": "x = 1"}

    first = client.post(
        f"/api/v1/sessions/{session_id}/submissions", json=body, headers={"Idempotency-Key": "s1"}
    )
    second = client.post(
        f"/api/v1/sessions/{session_id}/submissions", json=body, headers={"Idempotency-Key": "s1"}
    )

    assert first.status_code == 202 and second.status_code == 202
    assert second.json() == first.json()

    with Session(get_engine()) as db:
        artifacts = db.exec(select(Artifact).where(col(Artifact.session_id) == session_id)).all()
    assert len(artifacts) == 1

    # Without the key the second attempt is the old 409 — the protection that already
    # existed, and which this does not replace.
    assert client.post(f"/api/v1/sessions/{session_id}/submissions", json=body).status_code == 409


def test_a_failed_request_does_not_poison_its_key(created_sessions, user_id):
    """A refusal must stay retryable. A reservation left behind after a failure would
    answer every retry with a 409 for as long as the row lived."""
    client = sign_in(TestClient(app))
    before = session_count(user_id)

    # 422: a mode nothing can grade would produce an unfinishable session.
    bad = client.post(
        "/api/v1/sessions",
        json={"mode": "coding", "budget_minutes": 45, "focus_concepts": ["not-a-concept"]},
        headers={"Idempotency-Key": "recoverable"},
    )
    if bad.status_code == 201:
        # The planner tolerated the unknown concept; nothing to assert about failure.
        created_sessions.append(bad.json()["id"])
        pytest.skip("that request did not fail, so there is no poisoned key to test")

    with Session(get_engine()) as db:
        assert db.get(IdempotencyKey, (user_id, "POST /sessions", "recoverable")) is None

    retried = create(client, "recoverable")
    assert retried.status_code == 201, retried.text
    created_sessions.append(retried.json()["id"])
    assert session_count(user_id) == before + 1


def test_concurrent_retries_of_one_request_create_one_session(created_sessions, user_id):
    """The reason the primary key does the deciding.

    Two overlapping retries both find no row. Serially the check is correct; overlapped,
    only the database can refuse the second — the same finding as `artifacts` and `turns`
    in c4a71f2e83b0.
    """
    before = session_count(user_id)
    responses: list[Any] = []
    barrier = threading.Barrier(2)

    def go() -> None:
        client = sign_in(TestClient(app))
        barrier.wait()
        responses.append(create(client, "race"))

    threads = [threading.Thread(target=go) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    for response in responses:
        if response.status_code == 201:
            created_sessions.append(response.json()["id"])

    # One created it; the other either replayed it or was told it was in flight. What is
    # not allowed is two sessions.
    assert session_count(user_id) == before + 1
    assert sorted(r.status_code for r in responses) in ([201, 201], [201, 409])
