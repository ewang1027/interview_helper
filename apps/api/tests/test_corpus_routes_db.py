"""`GET /concepts`, `GET /corpus/items` and `GET /corpus/items/{id}`.

The route that matters most here is the last one, and what matters about it is what it
*withholds*: reading an item you have not been served defeats the measurement it exists
to take.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import sign_in, use_settings
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.db import get_engine
from api.main import app
from api.models import InterviewSession
from corpus.loader import load_concepts, load_items

pytestmark = pytest.mark.db


def get(path: str) -> Any:
    return sign_in(TestClient(app)).get(f"/api/v1{path}")


# --- /concepts --------------------------------------------------------------------------


def test_the_whole_taxonomy_comes_back_in_one_request():
    """The reason this exists: the dashboard was assembling 159 concepts from one weakness
    ranking per mode, four requests for static build-time content."""
    body = get("/concepts").json()
    assert body["total"] == len(load_concepts()) == 159
    assert {row["id"] for row in body["concepts"]} == {c.id for c in load_concepts()}


def test_every_concept_carries_what_the_ranking_could_not():
    row = next(r for r in get("/concepts").json()["concepts"] if r["id"] == "sliding-window")
    assert row["name"] and row["domain"] == "coding" and row["description"]
    assert isinstance(row["prereqs"], list)
    assert isinstance(row["unlocks"], list)


def test_unlocks_is_the_exact_reverse_of_prereqs():
    """Derived rather than stored, so it cannot drift from the edges it mirrors."""
    rows = {r["id"]: r for r in get("/concepts").json()["concepts"]}
    for concept_id, row in rows.items():
        for prereq in row["prereqs"]:
            assert concept_id in rows[prereq]["unlocks"], f"{prereq} should unlock {concept_id}"
        for unlocked in row["unlocks"]:
            assert concept_id in rows[unlocked]["prereqs"]


def test_servable_means_some_item_measures_it_as_a_primary_concept():
    """The gap between ranked and servable is a policy, not a corpus gap (docs/ADAPTIVE.md),
    and reporting it wrongly is a mistake this project has already made once."""
    body = get("/concepts").json()
    primary = {item.primary_concept for item in load_items()}
    assert {r["id"] for r in body["concepts"] if r["servable"]} == primary
    assert body["servable"] == len(primary)


def test_concepts_can_be_filtered_by_domain():
    body = get("/concepts?domain=quant").json()
    assert body["total"] == sum(1 for c in load_concepts() if c.domain == "quant")
    assert {r["domain"] for r in body["concepts"]} == {"quant"}


# --- /corpus/items ----------------------------------------------------------------------


def test_the_listing_never_carries_a_statement_for_any_item():
    """Not "redacted when unseen" — absent, always. A listing that carried statements
    would be a way to read every unseen item at once."""
    for row in get("/corpus/items").json()["items"]:
        assert "statement_md" not in row


def test_the_listing_filters_by_domain_and_by_concept():
    coding = get("/corpus/items?domain=coding").json()
    assert coding["total"] == sum(1 for i in load_items() if i.domain == "coding")

    windowed = get("/corpus/items?concept_id=sliding-window").json()
    assert windowed["total"] >= 1
    for row in windowed["items"]:
        assert "sliding-window" in [row["primary_concept"], *row["concepts"]]


# --- /corpus/items/{id} -----------------------------------------------------------------


def test_an_unseen_items_statement_is_withheld():
    unseen = next(row for row in get("/corpus/items").json()["items"] if not row["seen"])
    body = get(f"/corpus/items/{unseen['id']}").json()

    assert body["redacted"] is True
    assert body["statement_md"] is None
    # The title is not the secret — you can be told a problem exists.
    assert body["title"]


def test_hints_and_grading_are_never_returned_even_once_seen():
    """Being served an item is not a reason to be handed its solution."""
    body = get("/corpus/items").json()
    seen = next((row for row in body["items"] if row["seen"]), None)
    if seen is None:
        pytest.skip("this database has no served items to check")

    detail = get(f"/corpus/items/{seen['id']}").json()
    assert detail["redacted"] is False
    assert detail["statement_md"]
    for leaked in ("hints", "grading", "follow_ups"):
        assert leaked not in detail


def test_being_served_an_item_in_a_plan_is_what_reveals_it(created_sessions):
    """Read from the plan, not from artifacts: an item you were shown and did not answer
    has still been read, and redacting it afterwards would be theatre."""
    client = sign_in(TestClient(app))
    created = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 45})
    session_id = created.json()["id"]
    created_sessions.append(session_id)
    planned = created.json()["plan"]["items"][0]["item_id"]

    with Session(get_engine()) as db:
        row = db.get(InterviewSession, session_id)
        assert any(e["item_id"] == planned for e in row.plan["items"])

    detail = client.get(f"/api/v1/corpus/items/{planned}").json()
    assert detail["seen"] is True
    assert detail["statement_md"]


def test_an_unknown_item_is_a_404():
    assert get("/corpus/items/i.code.9999").status_code == 404


def test_every_corpus_route_needs_a_session_cookie():
    """A *configured* server with no cookie answers 401.

    `use_settings()` is what makes that the thing being tested. Without it the app has no
    `SESSION_SECRET` and every `/api/v1` route answers `503 not-configured` instead —
    correct, and a different assertion. This passed locally on a `.env` that has a secret
    and failed in CI, which builds its environment from nothing.
    """
    use_settings()
    anonymous = TestClient(app)
    for path in ("/concepts", "/corpus/items", "/corpus/items/i.code.0004"):
        assert anonymous.get(f"/api/v1{path}").status_code == 401, path
