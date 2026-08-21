"""A whole system-design session, which is the thing the rubric grader unlocked.

`create_session` refused every mode but `coding` until this landed, because a session in a
mode nothing can grade is an interview that can never complete. This is the proof that the
refusal has actually lifted rather than the constant having been edited — and since the
quant grader landed (2026-08-21) there is no mode left for it to refuse.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import sign_in, use_settings
from fakes import ScriptedModel, model_response, text_block
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api.db import get_engine
from api.events import bus
from api.grading.quant import DECLARED_CONFIDENCE
from api.grading.rubric import RUBRIC_CONFIDENCE
from api.main import app
from api.models import ConceptEvidence, Grading, LlmCall
from api.routes.sessions import get_model_client
from corpus.loader import load_items

pytestmark = pytest.mark.db

ITEMS = {item.id: item for item in load_items()}
MODEL_OVERRIDES: dict[str, Any] = {"model_grader": "us.anthropic.claude-sonnet-4-6"}

ANSWER = (
    "The delivery volume is what decides this: forty thousand notices a day against sixty "
    "subscribers each is two and a half million deliveries, and one bad notice is two "
    "million on its own. I would resolve the largest routes at read time and precompute "
    "the tail, because the write amplification on the largest ones is what falls over."
)


@pytest.fixture(autouse=True)
def _ledger():
    with Session(get_engine()) as db:
        before = set(db.exec(select(LlmCall.id)).all())
    yield
    with Session(get_engine()) as db:
        new = set(db.exec(select(LlmCall.id)).all()) - before
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
            db.commit()


def grader_saying(item_id: str, *, level: float, citation: str) -> ScriptedModel:
    grading = ITEMS[item_id].grading
    # `criteria` on a rubric item, `reasoning_rubric` on a quant one — the same shape in a
    # different place, judged by the same code.
    criteria = grading.get("criteria") or grading["reasoning_rubric"]
    payload = {
        "criteria": [
            {
                "id": criterion["id"],
                "demonstrated": True,
                "level": level,
                "citation": citation,
                "reasoning": "quoted above",
            }
            for criterion in criteria
        ],
        "summary": "Reasoned from the numbers.",
    }
    return ScriptedModel(model_response(text_block(json.dumps(payload))))


def test_a_design_session_can_be_created_submitted_and_graded(created_sessions):
    use_settings(**MODEL_OVERRIDES)
    client = sign_in(TestClient(app))

    created = client.post("/api/v1/sessions", json={"mode": "design", "budget_minutes": 45})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    created_sessions.append(session_id)
    planned = [entry["item_id"] for entry in created.json()["plan"]["items"]]
    assert planned and all(item_id.startswith("i.design.") for item_id in planned)

    item_id = planned[0]
    app.dependency_overrides[get_model_client] = lambda: grader_saying(
        item_id, level=4, citation="resolve the largest routes at read time"
    )
    submitted = client.post(
        f"/api/v1/sessions/{session_id}/submissions",
        json={"item_id": item_id, "kind": "design", "content": ANSWER},
    )
    assert submitted.status_code == 202, submitted.text

    detail = client.get(f"/api/v1/sessions/{session_id}").json()
    graded = next(entry for entry in detail["items"] if entry["item_id"] == item_id)
    assert graded["status"] == "graded"
    assert graded["score"] == pytest.approx(1.0)

    with Session(get_engine()) as db:
        grading = db.exec(select(Grading).order_by(col(Grading.id).desc())).first()
        assert grading is not None
        assert grading.grader_version == "rubric.llm@1"
        assert grading.detail["criteria"], "the score has to be explainable without a re-run"

        evidence = db.exec(
            select(ConceptEvidence).where(ConceptEvidence.session_id == session_id)
        ).all()
        assert evidence, "a graded rubric writes evidence"
        # Softer than a hidden test passing, which is the whole point of the number.
        assert all(row.confidence == RUBRIC_CONFIDENCE for row in evidence)
        assert {row.concept_id for row in evidence} == {
            criterion["concept"] for criterion in ITEMS[item_id].grading["criteria"]
        }

    events = [event.type for event in bus().since(session_id, 0)]
    assert "grading.started" in events and "grading.result" in events
    bus().forget(session_id)


def test_a_grader_that_cannot_reach_a_model_fails_the_grading_without_scoring_it(
    created_sessions,
):
    """docs/GRADING.md: a grader that crashed must not produce a fabricated score. The
    provider being unreachable is not the candidate's fault and must not be their zero."""
    use_settings(**MODEL_OVERRIDES)
    client = sign_in(TestClient(app))
    created = client.post("/api/v1/sessions", json={"mode": "design", "budget_minutes": 45})
    session_id = created.json()["id"]
    created_sessions.append(session_id)
    item_id = created.json()["plan"]["items"][0]["item_id"]

    class Unreachable:
        def __init__(self) -> None:
            self.messages = self

        def create(self, **kwargs: Any):
            import anthropic
            import httpx

            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x.invalid"))

    app.dependency_overrides[get_model_client] = Unreachable
    submitted = client.post(
        f"/api/v1/sessions/{session_id}/submissions",
        json={"item_id": item_id, "kind": "design", "content": ANSWER},
    )
    assert submitted.status_code == 202

    detail = client.get(f"/api/v1/sessions/{session_id}").json()
    graded = next(entry for entry in detail["items"] if entry["item_id"] == item_id)
    assert graded["status"] == "failed"
    assert graded["score"] is None
    assert "could not reach a model" in graded["detail"]["detail"]

    with Session(get_engine()) as db:
        assert not db.exec(
            select(ConceptEvidence).where(ConceptEvidence.session_id == session_id)
        ).all(), "a failed grading writes no evidence"
    bus().forget(session_id)


def test_a_quant_session_can_be_created_submitted_and_graded(created_sessions):
    """The mode this file used to prove was refused. Half a grader is not a grader, and
    quant needed both halves — a symbolic answer check and the derivation rubric — before a
    quant session could produce evidence anyone should trust. Both halves are visible in
    what it writes: one deterministic row for the number, one per criterion for the
    derivation, at two different confidences."""
    use_settings(**MODEL_OVERRIDES)
    client = sign_in(TestClient(app))

    created = client.post("/api/v1/sessions", json={"mode": "quant", "budget_minutes": 30})
    assert created.status_code == 201, created.text
    session_id = created.json()["id"]
    created_sessions.append(session_id)
    planned = [entry["item_id"] for entry in created.json()["plan"]["items"]]
    assert planned and all(item_id.startswith("i.quant.") for item_id in planned)

    item_id = planned[0]
    item = ITEMS[item_id]
    derivation = (
        "I conditioned on the next step from each state, which is the move that makes this "
        "tractable at all, and solved the resulting system.\n"
        f"Answer: {item.grading['answer']['exact']}"
    )
    app.dependency_overrides[get_model_client] = lambda: grader_saying(
        item_id, level=3, citation="conditioned on the next step from each state"
    )
    submitted = client.post(
        f"/api/v1/sessions/{session_id}/submissions",
        json={"item_id": item_id, "kind": "answer", "content": derivation},
    )
    assert submitted.status_code == 202, submitted.text

    detail = client.get(f"/api/v1/sessions/{session_id}").json()
    graded = next(entry for entry in detail["items"] if entry["item_id"] == item_id)
    assert graded["status"] == "graded"
    assert graded["score"] == pytest.approx(1.0)

    with Session(get_engine()) as db:
        grading = db.exec(select(Grading).order_by(col(Grading.id).desc())).first()
        assert grading is not None
        assert grading.grader_version == "quant.answer@1"
        assert grading.detail["answer"]["correct"] and grading.detail["answer"]["declared"]
        assert grading.detail["criteria"], "the score has to be explainable without a re-run"

        evidence = db.exec(
            select(ConceptEvidence).where(ConceptEvidence.session_id == session_id)
        ).all()
        by_confidence = sorted(row.confidence for row in evidence)
        # One deterministic reading of the number, and one per criterion of the derivation.
        assert by_confidence == [RUBRIC_CONFIDENCE] * len(item.grading["reasoning_rubric"]) + [
            DECLARED_CONFIDENCE
        ]
        assert item.primary_concept in {row.concept_id for row in evidence}

    bus().forget(session_id)


def test_a_behavioral_session_is_now_allowed(created_sessions):
    use_settings(**MODEL_OVERRIDES)
    client = sign_in(TestClient(app))
    created = client.post("/api/v1/sessions", json={"mode": "behavioral", "budget_minutes": 30})
    assert created.status_code == 201, created.text
    created_sessions.append(created.json()["id"])
    planned = [entry["item_id"] for entry in created.json()["plan"]["items"]]
    assert planned and all(item_id.startswith("i.behav.") for item_id in planned)
    bus().forget(created.json()["id"])
