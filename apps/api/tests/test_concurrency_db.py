"""Two gradings finishing at once. Marked `db`.

Every other database test runs through `TestClient`, which executes background tasks
inline — so the whole suite has only ever exercised the serial case, while a deployed
uvicorn runs `grade_artifact` in a threadpool and two submissions really do overlap.

What breaks under overlap is the design's central claim: `mastery` is a projection of
`concept_evidence`. Two transactions that read the same rating, each add their own delta
and commit will lose one of them — the evidence row survives, its effect does not, and a
later `recompute` legitimately produces a different table.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from conftest import sign_in
from fakes import FakeRunner
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api import mastery
from api import sessions as session_service
from api.db import get_engine
from api.main import app
from api.mastery import recompute
from api.models import Artifact, ConceptEvidence, Grading, Mastery
from api.routes.sessions import get_runner
from api.sessions import grade_artifact

pytestmark = pytest.mark.db

SOURCE = "def f(xs):\n    return xs\n"


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def snapshot(user_id: str) -> dict[str, tuple[float, int]]:
    with Session(get_engine()) as db:
        return {
            row.concept_id: (row.ability, row.observations)
            for row in db.exec(select(Mastery).where(Mastery.user_id == user_id)).all()
        }


def test_two_gradings_committing_at_once_still_replay_to_the_same_table(
    created_sessions, user_id, monkeypatch
) -> None:
    """The gate test, with the grading actually concurrent.

    All three coding items name `big-o-analysis`, so two submissions in flight both
    read-modify-write that concept's rating.

    The race window in production is microseconds wide, and a test that merely starts two
    threads together hits it perhaps one run in three — which is worse than useless as a
    guard, because it goes green while the bug is present. So `_row_for` is slowed to hold
    its read open: with the lock, the second grading waits outside and reads fresh state;
    without it, both read the same rating and one delta is lost. Run against a disabled
    lock this fails every time, which is the only reason to trust it passing.
    """
    app.dependency_overrides[get_runner] = lambda: FakeRunner()
    client = sign_in(TestClient(app))
    session = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 90}).json()
    created_sessions.append(session["id"])

    planned = [entry["item_id"] for entry in session["plan"]["items"]][:2]
    for item_id in planned:
        resp = client.post(
            f"/api/v1/sessions/{session['id']}/submissions",
            json={"item_id": item_id, "kind": "code", "language": "python", "content": SOURCE},
        )
        assert resp.status_code == 202, resp.text

    # `TestClient` graded those inline. Drop the evidence and the projection, then re-apply
    # the two gradings in parallel, which is what a threadpool-backed server does.
    with Session(get_engine()) as db:
        artifacts = [
            row.id
            for row in db.exec(select(Artifact).where(Artifact.session_id == session["id"])).all()
        ]
        db.exec(delete(ConceptEvidence).where(col(ConceptEvidence.session_id) == session["id"]))
        db.commit()
        recompute(db, user_id)

    original = mastery._row_for

    def slow_row_for(db: Session, user_id: str, concept_id: str):
        row = original(db, user_id, concept_id)
        time.sleep(0.05)
        return row

    monkeypatch.setattr(mastery, "_row_for", slow_row_for)

    start = threading.Barrier(len(artifacts))
    errors: list[BaseException] = []

    def run(artifact_id: str) -> None:
        try:
            start.wait(timeout=10)
            grade_artifact(artifact_id, FakeRunner())
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(artifact_id,)) for artifact_id in artifacts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    monkeypatch.undo()

    # Both gradings must have *succeeded*. Checking only that nothing was raised proves
    # nothing now that `grade_artifact` catches everything: a collision would be caught,
    # recorded as a failed grading, write no evidence — and the replay comparison below
    # would then agree with itself about nothing at all.
    with Session(get_engine()) as db:
        statuses = [
            row.status
            for row in db.exec(select(Grading).where(col(Grading.artifact_id).in_(artifacts))).all()
        ]
        written = db.exec(
            select(ConceptEvidence).where(ConceptEvidence.session_id == session["id"])
        ).all()
    # More gradings than artifacts: `TestClient` already graded these inline once, and the
    # re-grade above added a second row each. What matters is that none of them failed.
    assert "failed" not in statuses, statuses
    assert len(written) == 8, "four concepts per item, both items graded"

    incremental = snapshot(user_id)
    assert incremental, "both gradings vanished"

    with Session(get_engine()) as db:
        recompute(db, user_id)
    assert snapshot(user_id) == incremental


def test_a_grading_that_crashes_outside_the_grader_still_records_a_failure(
    created_sessions, user_id, monkeypatch
) -> None:
    """docs/GRADING.md's rule reaches past the grader itself.

    Anything raised after the grade is computed — an evidence insert, the projection
    update — used to roll the `gradings` row back with it, leaving the item reporting
    `"grading"` forever and refusing a retry with 409. The session could then only be
    ended, never completed.
    """
    app.dependency_overrides[get_runner] = lambda: FakeRunner()
    client = sign_in(TestClient(app))
    session = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 20}).json()
    created_sessions.append(session["id"])
    item_id = session["plan"]["items"][0]["item_id"]

    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("projection exploded")

    # Patched where it is *used*, not where it is defined: `api.sessions` imported the
    # name directly, so patching `api.mastery.apply_evidence` would rebind nothing.
    monkeypatch.setattr(session_service, "apply_evidence", explode)
    resp = client.post(
        f"/api/v1/sessions/{session['id']}/submissions",
        json={"item_id": item_id, "kind": "code", "language": "python", "content": SOURCE},
    )
    assert resp.status_code == 202
    monkeypatch.undo()

    detail = client.get(f"/api/v1/sessions/{session['id']}").json()
    row = next(entry for entry in detail["items"] if entry["item_id"] == item_id)
    assert row["status"] == "failed"
    assert row["score"] is None
    assert "projection exploded" in row["detail"]["detail"]

    # And the session is not stranded: every planned item reached a terminal grading.
    assert detail["state"] == "complete"

    with Session(get_engine()) as db:
        written = db.exec(
            select(ConceptEvidence).where(ConceptEvidence.session_id == session["id"])
        ).all()
    assert written == [], "a crashed grading must not leave evidence behind"
