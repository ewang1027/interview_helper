"""The session lifecycle against a live Postgres. Marked `db` — run via `make test-db`.

The executor is stubbed here, so these run without Docker and can produce outcomes real
containers cannot be asked for on demand (a timeout, an unreachable service). The real
sandbox path is `test_session_e2e.py`.

`TestClient` runs background tasks before returning the response, so a grade is already
written by the time a submission call returns — no polling, and no sleep-based flakiness.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api.db import get_engine
from api.executor_client import ProbeOutcome, RunResult
from api.main import app
from api.models import Artifact, ConceptEvidence, Grading, InterviewSession
from api.routes.sessions import get_runner

pytestmark = pytest.mark.db

REFERENCE = "def f(xs):\n    return xs\n"


class FakeRunner:
    """A `CodeRunner` whose answers the test chooses.

    Deliberately separate from the one in `test_grading_coding.py`: that one exists to
    exercise the grader's arithmetic, this one to drive the API. Both implement the same
    Protocol, which is what keeps them from drifting into different contracts.
    """

    def __init__(self, run: RunResult, probe: ProbeOutcome | None = None) -> None:
        self.run = run
        self.probe_result = probe or ProbeOutcome(verdict="matches", slope=1.0)

    def run_tests(
        self,
        *,
        source: str,
        entrypoint: str,
        tests: Sequence[Mapping[str, Any]],
        language: str = "python",
        test_selection: Sequence[str] = (),
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> RunResult:
        # `passed=0` in the canned result means "pass them all" — the fake does not know
        # how many cases an item ships until it is handed them.
        return self.run.model_copy(
            update={"total": len(tests), "passed": self.run.passed or len(tests)}
        )

    def probe(
        self,
        *,
        source: str,
        entrypoint: str,
        generator: str,
        sizes: Sequence[int],
        target: str | None,
        language: str = "python",
        repeats: int = 5,
        wall_ms: int | None = None,
        memory_mb: int | None = None,
    ) -> ProbeOutcome:
        return self.probe_result


def make_client(run: RunResult | None = None, probe: ProbeOutcome | None = None) -> TestClient:
    app.dependency_overrides[get_runner] = lambda: FakeRunner(
        run or RunResult(outcome="ok", passed=0, total=0), probe
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def created_sessions() -> list[str]:
    """Ids to delete afterwards.

    `concept_evidence` is append-only *in production* — the rule protects mastery from
    being hand-patched. A test that leaves its rows behind would instead corrupt the dev
    database's history with fabricated evidence, which is the same harm from the other
    direction.
    """
    ids: list[str] = []
    yield ids
    with Session(get_engine()) as db:
        artifact_ids = [
            a.id for a in db.exec(select(Artifact).where(col(Artifact.session_id).in_(ids))).all()
        ]
        if artifact_ids:
            db.exec(delete(Grading).where(col(Grading.artifact_id).in_(artifact_ids)))
        db.exec(delete(ConceptEvidence).where(col(ConceptEvidence.session_id).in_(ids)))
        db.exec(delete(Artifact).where(col(Artifact.session_id).in_(ids)))
        db.exec(delete(InterviewSession).where(col(InterviewSession.id).in_(ids)))
        db.commit()


def start(client: TestClient, sessions: list[str], **body: Any) -> dict[str, Any]:
    payload = {"mode": "coding", "budget_minutes": 90} | body
    resp = client.post("/api/v1/sessions", json=payload)
    assert resp.status_code == 201, resp.text
    created = resp.json()
    sessions.append(created["id"])
    return created


def submit(client: TestClient, session_id: str, item_id: str, content: str = REFERENCE):
    return client.post(
        f"/api/v1/sessions/{session_id}/submissions",
        json={"item_id": item_id, "kind": "code", "language": "python", "content": content},
    )


def test_a_session_returns_its_plan_up_front(created_sessions):
    """docs/API.md: opaque adaptation is untrustworthy adaptation. You see what it chose
    before you start — including, today, that it chose without adapting to anything."""
    client = make_client()
    created = start(client, created_sessions)

    assert created["state"] == "briefing"
    assert created["plan"]["adaptive"] is False
    assert len(created["plan"]["items"]) == 3


def test_a_graded_submission_writes_evidence_against_every_concept(created_sessions):
    client = make_client(RunResult(outcome="ok", passed=0, total=0))
    created = start(client, created_sessions)
    item_id = created["plan"]["items"][0]["item_id"]

    resp = submit(client, created["id"], item_id)
    assert resp.status_code == 202, resp.text
    assert resp.json()["state"] == "grading"

    detail = client.get(f"/api/v1/sessions/{created['id']}").json()
    graded = next(row for row in detail["items"] if row["item_id"] == item_id)
    assert graded["status"] == "graded"
    assert graded["score"] == pytest.approx(1.0)

    with Session(get_engine()) as db:
        rows = db.exec(
            select(ConceptEvidence).where(ConceptEvidence.session_id == created["id"])
        ).all()
    assert len(rows) == 4  # the item's four concepts
    assert {row.source for row in rows} == {"session_grading"}
    assert all(row.item_id == item_id for row in rows)


def test_a_failed_grading_is_recorded_and_writes_nothing(created_sessions):
    """The rule the whole schema change exists for: a timeout is a failed grading, not a
    zero, and mastery hears nothing about it."""
    client = make_client(RunResult(outcome="timeout", passed=0, total=0, detail="wall clock"))
    created = start(client, created_sessions)
    item_id = created["plan"]["items"][0]["item_id"]

    submit(client, created["id"], item_id)

    detail = client.get(f"/api/v1/sessions/{created['id']}").json()
    row = next(r for r in detail["items"] if r["item_id"] == item_id)
    assert row["status"] == "failed"
    assert row["score"] is None

    with Session(get_engine()) as db:
        evidence = db.exec(
            select(ConceptEvidence).where(ConceptEvidence.session_id == created["id"])
        ).all()
        gradings = db.exec(
            select(Grading).where(col(Grading.artifact_id).in_([row["artifact_id"]]))
        ).all()
    assert evidence == []
    assert [(g.status, g.score) for g in gradings] == [("failed", None)]


def test_the_session_completes_when_every_planned_item_is_terminal(created_sessions):
    client = make_client()
    created = start(client, created_sessions)

    for entry in created["plan"]["items"]:
        assert submit(client, created["id"], entry["item_id"]).status_code == 202

    detail = client.get(f"/api/v1/sessions/{created['id']}").json()
    assert detail["state"] == "complete"
    assert detail["ended_at"] is not None


def test_the_report_is_refused_until_the_session_ends(created_sessions):
    client = make_client()
    created = start(client, created_sessions)

    resp = client.get(f"/api/v1/sessions/{created['id']}/report")
    assert resp.status_code == 409
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"].endswith("/wrong-state")


def test_the_report_carries_the_evidence_it_wrote(created_sessions):
    client = make_client()
    created = start(client, created_sessions)
    for entry in created["plan"]["items"]:
        submit(client, created["id"], entry["item_id"])

    report = client.get(f"/api/v1/sessions/{created['id']}/report").json()
    assert report["graded"] == 3
    assert report["mean_score"] == pytest.approx(1.0)
    assert len(report["evidence"]) == 11  # 4 + 4 + 3 concepts across the three items
    assert any("rubric" in note for note in report["notes"])


def test_ending_early_abandons_the_session_and_keeps_what_was_graded(created_sessions):
    """docs/API.md: a session you quit halfway through is real data about the part you did."""
    client = make_client()
    created = start(client, created_sessions)
    submit(client, created["id"], created["plan"]["items"][0]["item_id"])

    ended = client.post(f"/api/v1/sessions/{created['id']}/end")
    assert ended.status_code == 200
    assert ended.json()["state"] == "abandoned"

    report = client.get(f"/api/v1/sessions/{created['id']}/report").json()
    assert report["graded"] == 1
    assert report["not_attempted"] == 2
    assert len(report["evidence"]) == 4


def test_a_second_submission_for_the_same_item_is_refused(created_sessions):
    """Not idempotency, but it refuses the harmful half of it: one item cannot write two
    sets of evidence into one session."""
    client = make_client()
    created = start(client, created_sessions)
    item_id = created["plan"]["items"][0]["item_id"]

    assert submit(client, created["id"], item_id).status_code == 202
    again = submit(client, created["id"], item_id)
    assert again.status_code == 409
    assert again.json()["type"].endswith("/wrong-state")

    with Session(get_engine()) as db:
        rows = db.exec(
            select(ConceptEvidence).where(ConceptEvidence.session_id == created["id"])
        ).all()
    assert len(rows) == 4


def test_a_submission_outside_the_plan_is_unprocessable(created_sessions):
    client = make_client()
    created = start(client, created_sessions)

    resp = submit(client, created["id"], "i.quant.0001")
    assert resp.status_code == 422
    assert resp.json()["type"].endswith("/unprocessable")


def test_a_submission_to_an_ended_session_is_refused(created_sessions):
    client = make_client()
    created = start(client, created_sessions)
    client.post(f"/api/v1/sessions/{created['id']}/end")

    resp = submit(client, created["id"], created["plan"]["items"][0]["item_id"])
    assert resp.status_code == 409


def test_an_unknown_session_is_a_problem_json_404(created_sessions):
    client = make_client()
    resp = client.get("/api/v1/sessions/01JZZZZZZZZZZZZZZZZZZZZZZZ")
    assert resp.status_code == 404
    assert resp.json()["type"].endswith("/not-found")


def test_a_mode_with_no_grader_is_refused_with_the_reason(created_sessions):
    """A quant session would plan real items and then dead-end at the first submission,
    because no quant grader exists. Refusing up front says so."""
    client = make_client()
    resp = client.post("/api/v1/sessions", json={"mode": "quant", "budget_minutes": 45})
    assert resp.status_code == 422
    assert "no grader" in resp.json()["detail"].lower()


def test_sessions_list_newest_first(created_sessions):
    client = make_client()
    first = start(client, created_sessions)
    second = start(client, created_sessions)

    listed = client.get("/api/v1/sessions", params={"limit": 2}).json()["sessions"]
    assert [row["id"] for row in listed] == [second["id"], first["id"]]
