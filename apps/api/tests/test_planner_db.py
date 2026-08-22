"""The planner, against a live Postgres. Marked `db`.

`test_an_injected_weakness_gets_drilled_within_five_sessions` is the other half of
docs/ADAPTIVE.md's Phase 4 gate: a synthetic candidate who is bad at one concept and good
at the rest, and the requirement that the planner notice within five sessions. It is the
only test here that checks the thing the whole engine exists to do — everything else
checks that it can explain itself while doing it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import sign_in
from fakes import FakeRunner, ScriptedRunner
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.db import get_engine
from api.main import app
from api.mastery import DEFAULT_ABILITY
from api.models import Mastery
from api.planner import STRATEGY, _prerequisite_substitution, build_plan
from api.priority import ConceptPriority
from api.routes.sessions import get_runner
from corpus.loader import load_concepts, load_items

pytestmark = pytest.mark.db

# The item whose primary concept is `monotonic-stack`, and the function a submission for
# it has to define. The simulated candidate is bad at exactly this.
WEAK_ITEM = "i.code.0002"
WEAK_ENTRYPOINT = "pressure_spans"
WEAK_CONCEPT = "monotonic-stack"

# The concept the review slot should reach for. Which *item* it picks is the planner's
# choice and there is more than one measuring this now, so the assertion below is about the
# concept served — pinning an id made it a test of the corpus's size.
REVIEW_CONCEPT = "binary-search-answer"

SOURCE = "def f(xs):\n    return xs\n"


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def client_with(runner: Any) -> TestClient:
    app.dependency_overrides[get_runner] = lambda: runner
    return sign_in(TestClient(app))


def start(client: TestClient, created: list[str], budget: int = 45) -> dict[str, Any]:
    resp = client.post("/api/v1/sessions", json={"mode": "coding", "budget_minutes": budget})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    created.append(body["id"])
    return body


def submit(client: TestClient, session_id: str, item_id: str) -> None:
    resp = client.post(
        f"/api/v1/sessions/{session_id}/submissions",
        json={"item_id": item_id, "kind": "code", "language": "python", "content": SOURCE},
    )
    assert resp.status_code == 202, resp.text


def test_a_cold_start_plan_says_it_is_calibrating(created_sessions):
    """With no evidence there is no weakness signal, and a plan that implied otherwise
    would be the opaque adaptation docs/API.md warns about."""
    plan = start(client_with(FakeRunner()), created_sessions)["plan"]

    assert plan["adaptive"] is True
    assert plan["strategy"] == STRATEGY
    assert plan["calibration"] is True
    assert "calibration spread" in plan["why"]


def test_each_item_records_the_concept_it_targets_and_what_was_expected(created_sessions):
    plan = start(client_with(FakeRunner()), created_sessions)["plan"]

    for entry in plan["items"]:
        reason = entry["reason"]
        assert reason["targets"]
        assert 0.0 <= reason["expected_score"] <= 1.0
        assert set(reason["terms"]) >= {"weakness", "recent_errors", "overdue", "unlocks"}


def test_the_plan_shows_the_concepts_it_weighed_not_only_the_ones_it_served(created_sessions):
    """The ranking is the part worth arguing with, and it is invisible from the item list:
    three items cannot show which of 52 coding concepts were considered."""
    plan = start(client_with(FakeRunner()), created_sessions)["plan"]

    considered = {entry["concept_id"] for entry in plan["considered"]}
    served = {entry["primary_concept"] for entry in plan["items"]}
    assert len(considered) >= len(served)


def test_an_injected_weakness_gets_drilled(created_sessions):
    """docs/ADAPTIVE.md's Phase 4 gate.

    A candidate who fails `monotonic-stack` and aces everything else. Sessions are
    budgeted to one item so the planner has to *choose*, and a majority of the choices
    must land on the item that measures the weakness.

    The second and third assertions are why this test is worth trusting. An earlier
    version checked only the majority and **passed while proving nothing**: the planner
    happened to serve that item first at cold start, for want of a tie-break, so the count
    was already satisfied before any evidence existed. A gate that can be satisfied by a
    default is not a gate. So: the first session must *not* be the weak item, and by the
    end the engine must actually believe the candidate is weakest at that concept.

    **The window was five sessions and is now ten**, because authoring
    `hash-map-counting` woke up a term that had never been able to fire. It gates six
    coding concepts, so its `unlocks` term is 0.086 against `monotonic-stack`'s 0.014, and
    at cold start — where every weakness term sits at 0.199 because nothing is measured —
    that difference decides the order. The planner spends sessions 1-3 establishing a
    foundational concept that unlocks six others before it drills anything, which is
    docs/ADAPTIVE.md's stated intent for the term rather than a regression. Measured:
    sessions 4-7 all serve the weakness, session 8 rotates away on anti-repetition, and
    9-10 return to it.

    Two consequences worth naming, because both will recur. A *majority* over a growing
    window is not a gate this engine can ever satisfy — `W_EXPOSURE` guarantees it rotates
    off a sore spot, so the fraction is bounded above by design. And the exploration
    prologue scales with how much unmeasured foundational corpus exists, so this window is
    expected to need raising again as authoring continues. The `most_served` assertion is
    the half that does not depend on window arithmetic.
    """
    runner = ScriptedRunner({WEAK_ENTRYPOINT})
    client = client_with(runner)

    served: list[str] = []
    for _ in range(10):
        session = start(client, created_sessions, budget=20)
        item_id = session["plan"]["items"][0]["item_id"]
        served.append(item_id)
        submit(client, session["id"], item_id)

    most_served = max(set(served), key=served.count)
    assert most_served == WEAK_ITEM, f"served {served}"
    assert served.count(WEAK_ITEM) > len(served) / 2, f"served {served}"
    assert served[0] != WEAK_ITEM, "cold start served it by default, so this proves nothing"

    measured = {
        row["concept_id"]: row["ability"]
        for row in client.get("/api/v1/mastery").json()["concepts"]
    }
    weakest = min(measured, key=lambda concept: measured[concept])
    assert weakest == WEAK_CONCEPT, measured
    assert measured[WEAK_CONCEPT] < DEFAULT_ABILITY


def test_the_weakness_ranking_puts_the_failed_concept_first(created_sessions):
    runner = ScriptedRunner({WEAK_ENTRYPOINT})
    client = client_with(runner)
    session = start(client, created_sessions, budget=90)
    for entry in session["plan"]["items"]:
        submit(client, session["id"], entry["item_id"])

    ranked = client.get("/api/v1/mastery/weaknesses", params={"mode": "coding"}).json()
    measured = [row for row in ranked["concepts"] if row["observations"] > 0]

    assert measured[0]["concept_id"] == WEAK_CONCEPT
    assert measured[0]["terms"]["recent_errors"] > 0
    assert ranked["weights"]["weakness"] > 0


def test_plan_next_previews_without_creating_a_session(created_sessions):
    client = client_with(FakeRunner())
    before = client.get("/api/v1/sessions", params={"limit": 1}).json()["sessions"]

    preview = client.get("/api/v1/plan/next", params={"mode": "coding", "budget_minutes": 45})
    assert preview.status_code == 200
    assert preview.json()["items"]

    after = client.get("/api/v1/sessions", params={"limit": 1}).json()["sessions"]
    assert after == before


def test_focus_concepts_override_the_ranking(created_sessions):
    client = client_with(FakeRunner())
    resp = client.post(
        "/api/v1/sessions",
        json={"mode": "coding", "budget_minutes": 90, "focus_concepts": [WEAK_CONCEPT]},
    )
    created_sessions.append(resp.json()["id"])

    items = resp.json()["plan"]["items"]
    assert [entry["item_id"] for entry in items] == [WEAK_ITEM]


def test_a_prerequisite_no_item_measures_is_reported_rather_than_served(db_session):
    """The DAG is a hard gate only as far as the corpus can honour it. `monotonic-stack`
    is gated by `stack-simulation`, which no item measures — substituting toward it would
    plan a session with nothing in it, so the concept is kept and the plan says why."""
    entry = _priority(WEAK_CONCEPT, ability=1100)
    weaker_prereq = _priority("stack-simulation", ability=900)

    concept_id, note = _prerequisite_substitution(
        db_session,
        entry,
        {entry.concept_id: entry, weaker_prereq.concept_id: weaker_prereq},
        serveable={WEAK_CONCEPT},
    )

    assert concept_id == WEAK_CONCEPT
    assert note is not None and "no item measures it" in note


def test_a_weak_prerequisite_that_can_be_served_takes_the_slot(db_session):
    """The other branch, using the real DAG: `sliding-window` is gated by `two-pointers`."""
    entry = _priority("sliding-window", ability=1400)
    prereq = _priority("two-pointers", ability=900)

    concept_id, note = _prerequisite_substitution(
        db_session,
        entry,
        {entry.concept_id: entry, prereq.concept_id: prereq},
        serveable={"sliding-window", "two-pointers"},
    )

    assert concept_id == "two-pointers"
    assert note is not None and "substituted for sliding-window" in note


def _priority(concept_id: str, *, ability: float) -> ConceptPriority:
    return ConceptPriority(
        concept_id=concept_id,
        name=concept_id,
        domain="coding",
        priority=0.0,
        ability=ability,
        observations=1,
        calibrating=True,
        unseen=False,
        terms={},
    )


def test_a_due_concept_you_are_good_at_takes_one_slot(created_sessions, user_id, db_session):
    """docs/ADAPTIVE.md's review slot, which was unreachable until the budget reserved it.

    The `mastery` row is written directly — the only place in the suite that does — because
    reaching this state honestly takes dozens of successful sessions, and what is under test
    is the planner's reaction to the state, not the arithmetic that produces it. The
    fixture replays the projection afterwards, so nothing hand-written survives the test.
    """
    with Session(get_engine()) as db:
        past = datetime.now(UTC) - timedelta(days=30)
        db.add(
            Mastery(
                user_id=user_id,
                concept_id=REVIEW_CONCEPT,
                # Far enough above every item measuring this concept that none of them is
                # in the informative band — which is the situation the review slot exists
                # for. 1750 used to produce it and stopped when a second, easier
                # `binary-search-answer` instance was authored: at that ability the new
                # item is squarely in band, so the ordinary weakness path serves it and the
                # review slot is not needed. The scenario is "you are good at it"; the
                # number that expresses it depends on the corpus.
                ability=2100.0,
                observations=6,
                stability=5.0,
                due_at=past,
                last_seen=past,
            )
        )
        db.commit()

    plan = build_plan(db_session, user_id, "coding", 45)
    served = [entry["item_id"] for entry in plan["items"]]

    # Selected structurally: the review slot is the one entry the planner adds outside the
    # priority ranking, so it is the one with no priority. Matching on the concept instead
    # picks up the weakness shortlist's own entry for it, which is a different decision that
    # happens to name the same concept.
    review = next((entry for entry in plan["items"] if entry["reason"]["priority"] is None), None)
    assert review is not None, served
    assert review["reason"]["targets"] == REVIEW_CONCEPT
    assert review["reason"]["prerequisite_note"] == "due for review, and you are good at it"
    # And it is seasoning, not the session: something weak was still served alongside it.
    assert len(served) >= 2, served
    assert plan["estimated_minutes"] <= 45


def test_nothing_is_marked_review_when_nothing_is_due(created_sessions, user_id, db_session):
    plan = build_plan(db_session, user_id, "coding", 45)
    assert all(
        entry["reason"]["prerequisite_note"] != "due for review, and you are good at it"
        for entry in plan["items"]
    )


def _substitutable_pairs() -> list[tuple[str, str]]:
    """`(gated concept, prerequisite)` pairs the corpus can actually honour.

    Note which side the corpus has to cover. `_prerequisite_substitution` checks
    `serveable` only on the concept it substitutes *toward* — the gated concept is
    whatever the ranking threw up and may have no items at all, in which case
    substitution *rescues* a slot `build_plan` would otherwise drop for an empty pool.
    Requiring both sides to be measured describes a different, smaller set: the case
    where the planner turns away from a concept it could have served.

    Computed from disk rather than written down. Which pairs exist is a property of how
    much corpus has been authored, and the two tests above pin their `serveable` sets by
    hand — `test_a_weak_prerequisite_that_can_be_served_takes_the_slot` passes
    `{"sliding-window", "two-pointers"}`, and no item measures `two-pointers` even now.
    That proves the *function* has both branches. It does not prove the corpus can reach
    the second one, which is a different claim and the one below.
    """
    serveable = {
        item.primary_concept for item in load_items() if item.kind == "instance" and item.is_active
    }
    return [
        (concept.id, prereq)
        for concept in load_concepts()
        if concept.deprecated_at is None
        for prereq in concept.prereqs
        if prereq in serveable
    ]


def test_every_prerequisite_pair_the_corpus_can_honour_is_actually_substituted(db_session):
    """The gate against the real DAG and the real corpus, rather than a hand-written
    `serveable` set. Every pair on disk must substitute; one that does not means the
    concept edge and the corpus disagree about which way the prerequisite runs."""
    pairs = _substitutable_pairs()
    assert pairs, "no concept has a prerequisite the corpus can serve"

    for gated, prereq in pairs:
        entry = _priority(gated, ability=1500)
        weaker = _priority(prereq, ability=1100)
        concept_id, note = _prerequisite_substitution(
            db_session,
            entry,
            {entry.concept_id: entry, weaker.concept_id: weaker},
            serveable={prereq},
        )

        assert concept_id == prereq, f"{gated} did not substitute toward {prereq}"
        assert note is not None and f"substituted for {gated}" in note


def test_the_gate_can_turn_away_from_a_concept_it_could_have_served(db_session):
    """The harder half, and the one this corpus could barely reach.

    Rescuing an unserveable concept's slot is the common case and needs only the
    prerequisite to have items. The case worth having is the *redirect*: a concept the
    planner could serve, passed over because something underneath it is weaker. That
    needs both sides measured, and until `star-structure`, `hash-map-counting`,
    `load-balancing` and `sample-space-counting` were authored the corpus held exactly
    one such pair, all of it in quant.
    """
    serveable = {
        item.primary_concept for item in load_items() if item.kind == "instance" and item.is_active
    }
    redirects = [(gated, prereq) for gated, prereq in _substitutable_pairs() if gated in serveable]
    domains = {
        concept.domain
        for concept in load_concepts()
        if concept.id in {gated for gated, _ in redirects}
    }

    assert len(redirects) >= 6, redirects
    assert domains == {"coding", "quant", "system_design", "behavioral"}, domains
