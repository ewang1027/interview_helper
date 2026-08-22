"""The projection against a live Postgres. Marked `db`.

The one that matters here is `test_recompute_reproduces_the_projection_exactly` — half of
docs/ADAPTIVE.md's Phase 4 gate. Everything the design claims rests on it: if the table
cannot be rebuilt from `concept_evidence` alone, then "correct the evidence and replay"
is not a repair strategy, and every number in `mastery` becomes a fact nobody can check.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import sign_in
from fakes import FakeRunner
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from api.db import get_engine
from api.executor_client import RunResult
from api.main import app
from api.mastery import DEFAULT_ABILITY, K_ITEM, apply_evidence, lock_projection
from api.models import ConceptEvidence, Item, Mastery
from api.routes.sessions import get_runner
from api.seed import seed

pytestmark = pytest.mark.db

ITEM = "i.code.0002"
PRIMARY = "monotonic-stack"
SECONDARY = "stack-simulation"
SOURCE = "def pressure_spans(readings):\n    return readings\n"


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def client_for(run: RunResult | None = None) -> TestClient:
    app.dependency_overrides[get_runner] = lambda: FakeRunner(run)
    return sign_in(TestClient(app))


def run_session(
    client: TestClient, created: list[str], *, only: tuple[str, ...] | None = None
) -> dict[str, Any]:
    """Start a session and submit to every planned item, or just the ones named."""
    session = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 90}).json()
    created.append(session["id"])
    planned = [entry["item_id"] for entry in session["plan"]["items"]]
    wanted = [item_id for item_id in planned if only is None or item_id in only]
    assert wanted, f"{only} is not in the plan {planned}"
    for item_id in wanted:
        resp = client.post(
            f"/api/v1/sessions/{session['id']}/submissions",
            json={
                "item_id": item_id,
                "kind": "code",
                "language": "python",
                "content": SOURCE,
            },
        )
        assert resp.status_code == 202, resp.text
    return session


def snapshot(user_id: str) -> dict[str, Any]:
    """Every column the projection owns, `fsrs_card` included.

    The card is in here deliberately. Comparing only the four derived numbers let a real
    divergence hide: `fsrs.Card()` stamps its `card_id` from the wall clock, so a rebuilt
    row differed from the row it was supposed to reproduce while every number computed
    from it matched. A replay gate that skips a column is a gate with a hole in it.
    """
    with Session(get_engine()) as db:
        mastery = {
            row.concept_id: (
                row.ability,
                row.observations,
                row.stability,
                row.due_at,
                # `last_seen` is a column the projection owns and this gate did not read
                # it — the docstring above says a gate that skips a column is a gate with
                # a hole in it, and `last_seen` was added after that sentence was written.
                row.last_seen,
                row.fsrs_card,
            )
            for row in db.exec(select(Mastery).where(Mastery.user_id == user_id)).all()
        }
        items = {row.id: row.elo for row in db.exec(select(Item)).all()}
    return {"mastery": mastery, "items": items}


def test_a_graded_session_moves_ability_and_schedules_a_review(created_sessions, user_id):
    run_session(client_for(), created_sessions)

    with Session(get_engine()) as db:
        row = db.get(Mastery, (user_id, PRIMARY))
    assert row is not None
    # A full-marks answer to an item rated above the default ability beats expectation, so
    # the estimate goes up rather than down.
    assert row.ability > DEFAULT_ABILITY
    assert row.observations == 1
    assert row.due_at is not None and row.stability is not None
    assert row.due_at > row.last_seen


def test_confidence_decides_how_far_one_result_moves_a_rating(created_sessions, user_id):
    """Same submission, same score, two concepts: the item is *chiefly* a measurement of
    its primary concept, and the rating has to move accordingly or the distinction the
    grader draws is thrown away one layer later."""
    run_session(client_for(), created_sessions, only=(ITEM,))

    with Session(get_engine()) as db:
        primary = db.get(Mastery, (user_id, PRIMARY))
        secondary = db.get(Mastery, (user_id, SECONDARY))
    assert primary is not None and secondary is not None
    assert primary.ability - DEFAULT_ABILITY > secondary.ability - DEFAULT_ABILITY > 0


def test_recompute_reproduces_the_projection_exactly(created_sessions, user_id):
    """docs/ADAPTIVE.md's replay gate: the incremental projection and a from-scratch
    rebuild must agree, down to the due date."""
    client = client_for()
    run_session(client, created_sessions)
    incremental = snapshot(user_id)

    result = client.post("/api/v1/mastery/recompute").json()
    assert result["evidence_replayed"] >= 11
    assert result["concepts"] == len(incremental["mastery"])

    assert snapshot(user_id) == incremental


def test_recompute_is_idempotent(created_sessions, user_id):
    client = client_for()
    run_session(client, created_sessions)

    client.post("/api/v1/mastery/recompute")
    once = snapshot(user_id)
    client.post("/api/v1/mastery/recompute")

    assert snapshot(user_id) == once


def test_recompute_reads_evidence_and_never_writes_it(created_sessions, user_id):
    """`concept_evidence` is append-only. A rebuild that touched it would be rewriting
    the history it is supposed to be derived from."""
    client = client_for()
    run_session(client, created_sessions)

    with Session(get_engine()) as db:
        before = [
            (row.id, row.concept_id, row.score, row.confidence, row.ts)
            for row in db.exec(select(ConceptEvidence).order_by(ConceptEvidence.id)).all()
        ]

    client.post("/api/v1/mastery/recompute")

    with Session(get_engine()) as db:
        after = [
            (row.id, row.concept_id, row.score, row.confidence, row.ts)
            for row in db.exec(select(ConceptEvidence).order_by(ConceptEvidence.id)).all()
        ]
    assert after == before


def test_an_items_rating_drifts_from_its_seed_and_rebuilds_from_evidence(created_sessions, user_id):
    """Item ratings are a projection too — `difficulty_elo` is the author's prior and
    `elo` is what real outcomes made of it. A rebuild that reset only half the state would
    produce a table no replay could reproduce.

    The `<= K_ITEM` bound is a regression test, not a formality: one graded submission
    writes one evidence row *per concept the item names*, and updating the item on each of
    them drifted its rating four times faster than an item naming a single concept — 9.1
    points against a K_ITEM of 4. An item rating is a fact about the attempt, so it moves
    once per attempt."""
    client = client_for()
    with Session(get_engine()) as db:
        item = db.get(Item, ITEM)
        assert item is not None
        before, seed = item.elo, item.difficulty_elo

    run_session(client, created_sessions)

    with Session(get_engine()) as db:
        item = db.get(Item, ITEM)
        assert item is not None
        drifted = item.elo
    # Answered above expectation, so the item is now rated slightly easier than it was.
    assert drifted < before
    with Session(get_engine()) as db:
        rows = db.exec(select(ConceptEvidence).where(ConceptEvidence.item_id == ITEM)).all()
    assert len(rows) == 4, "the item writes one evidence row per concept it names"
    assert abs(drifted - seed) <= K_ITEM, "but its own rating moved once, not four times"

    drift_snapshot = snapshot(user_id)
    client.post("/api/v1/mastery/recompute")
    assert snapshot(user_id)["items"][ITEM] == pytest.approx(drift_snapshot["items"][ITEM])


def test_an_items_rating_moves_once_however_many_rows_name_its_primary_concept(
    created_sessions, user_id
):
    """The rule above is "one move per attempt"; the code said "one move per row naming the
    primary concept". Those were the same condition only while one row per concept was the
    only evidence shape there was.

    The quant grader broke that: it writes a deterministic row for the answer *and* a rubric
    row per criterion, and a criterion may name the primary concept too — `i.quant.0002`
    produces three rows naming `expected-value-decision`. Each satisfied the old test, so
    the rating moved three times per attempt. Written against a coding item because the
    invariant is the projection's, not any one grader's."""
    client = client_for()
    session = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": 90})
    session_id = session.json()["id"]
    created_sessions.append(session_id)

    with Session(get_engine()) as db:
        item = db.get(Item, ITEM)
        assert item is not None
        before = item.elo

        lock_projection(db)
        rows = [
            ConceptEvidence(
                concept_id=PRIMARY,
                source="session_grading",
                item_id=ITEM,
                session_id=session_id,
                score=1.0,
                confidence=0.9,
                grader_version="test.three-rows@1",
            )
            for _ in range(3)
        ]
        for row in rows:
            db.add(row)
        db.flush()
        for row in rows:
            apply_evidence(db, row, user_id=user_id)
        db.commit()

    with Session(get_engine()) as db:
        item = db.get(Item, ITEM)
        assert item is not None
        moved = item.elo
    assert abs(moved - before) <= K_ITEM, "three readings of one attempt, one rating move"

    # And a rebuild has to reach the same number, or the rule holds in the live path only
    # and the projection stops being reproducible — which is the whole design.
    client.post("/api/v1/mastery/recompute")
    with Session(get_engine()) as db:
        item = db.get(Item, ITEM)
        assert item is not None
        assert item.elo == pytest.approx(moved)


def test_a_failed_grading_leaves_the_projection_untouched(created_sessions, user_id):
    """No evidence, no rating change. A timeout says nothing about the candidate."""
    before = snapshot(user_id)
    run_session(
        client_for(RunResult(outcome="timeout", passed=0, total=0, detail="wall clock")),
        created_sessions,
    )

    assert snapshot(user_id) == before


def test_the_concept_endpoint_shows_the_evidence_behind_the_number(created_sessions, user_id):
    """The feature that makes the engine auditable: every number traces to graded
    artifacts you can re-read."""
    client = client_for()
    session = run_session(client, created_sessions, only=(ITEM,))

    body = client.get(f"/api/v1/mastery/{PRIMARY}").json()
    assert body["mastery"]["observations"] == 1
    assert body["mastery"]["calibrating"] is True
    assert len(body["evidence"]) == 1
    assert body["evidence"][0]["session_id"] == session["id"]
    assert body["evidence"][0]["source"] == "session_grading"
    assert body["evidence"][0]["grader_version"].startswith("coding.deterministic")


def test_an_unknown_concept_is_a_problem_json_404(created_sessions):
    resp = client_for().get("/api/v1/mastery/no-such-concept")
    assert resp.status_code == 404
    assert resp.json()["type"].endswith("/not-found")


def test_the_mastery_list_says_how_little_it_knows(created_sessions, user_id):
    """ "Four concepts, weakest first" reads very differently once you know the taxonomy
    has 159 and the rest have never been measured."""
    client = client_for()
    run_session(client, created_sessions, only=(ITEM,))

    body = client.get("/api/v1/mastery").json()
    assert body["measured"] == 4
    assert body["calibrating"] == 4
    abilities = [row["ability"] for row in body["concepts"]]
    assert abilities == sorted(abilities)


def test_a_re_rated_item_does_not_break_the_replay_invariant(created_sessions, user_id):
    """docs/ADAPTIVE.md's central claim: mastery is derived, and a replay must reproduce
    the live table exactly.

    `items.elo` drifts from real outcomes and a re-seed deliberately leaves it alone — but
    a re-seed *does* refresh `difficulty_elo`, and `recompute` rebuilds `elo` as
    `difficulty_elo` plus a replay. So re-rating an existing item left the live table
    standing on the old prior and every replay on the new one. Measured before the fix:
    one full-marks attempt, a prior moved 1600 -> 1680, and the replay returned item elo
    1677.56 against a live 1597.94, with the concept's ability 4.64 Elo apart.

    Nothing could see it. The suite replays after every test, so a dev database is
    permanently rebased and only a long-lived one diverges.
    """
    item_id = "i.code.0002"
    with Session(get_engine()) as db:
        item = db.get(Item, item_id)
        assert item is not None
        original = item.difficulty_elo
        item.difficulty_elo = original + 80
        db.add(item)
        db.commit()

    try:
        with Session(get_engine()) as db:
            rebased = seed(db)
        assert item_id in rebased, "a changed corpus prior has to be reported"
    finally:
        with Session(get_engine()) as db:
            item = db.get(Item, item_id)
            assert item is not None
            item.difficulty_elo = original
            db.add(item)
            db.commit()
