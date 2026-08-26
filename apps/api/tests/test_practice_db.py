"""The practice log's flows against a live Postgres, with a scripted classifier.

The interesting thing here is not the interval arithmetic — `test_practice.py` pins that.
It is the confidence gate and what it protects: `concept_evidence` is immutable, so a row
written against a tag that turns out to be wrong is a permanent fact about your mastery
with no way to retract it. Every test below that looks like it is about `status` is really
about that.

Teardown removes exactly the rows these tests caused and then **replays the projection**,
because `mastery` is an aggregate of evidence that cannot be un-summed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import sign_in, use_settings
from fakes import ScriptedModel, model_response, text_block
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api import practice
from api.db import get_engine
from api.main import app
from api.mastery import recompute
from api.models import ConceptEvidence, LlmCall, Mastery, PracticeProblem, PracticeSolve
from api.routes.practice import get_classifier
from api.settings import get_settings
from api.users import single_user

pytestmark = pytest.mark.db

MODEL = "us.anthropic.claude-sonnet-4-6"
PRIMARY = "sliding-window"
SECONDARY = "two-pointers"


def classifier(
    *,
    primary: str = PRIMARY,
    secondaries: list[str] | None = None,
    confidence: float = 0.9,
    times: int = 4,
) -> ScriptedModel:
    """A classifier that answers the same way every time. Scripted several deep because a
    test that logs two problems makes two calls, and the fake refuses to invent a third."""
    payload = {
        "primary_concept_id": primary,
        "secondary_concept_ids": secondaries if secondaries is not None else [SECONDARY],
        "confidence": confidence,
        "reasoning": "the title names the technique outright",
    }
    return ScriptedModel(*[model_response(text_block(json.dumps(payload))) for _ in range(times)])


class DeadProvider:
    """A client whose every call raises, for the case where classification is unavailable."""

    def __init__(self) -> None:
        self.messages = self

    def create(self, **_: Any) -> Any:
        raise RuntimeError("no provider configured")


@pytest.fixture
def logged():
    """Every practice problem a test creates. Teardown removes it, its solves, its evidence
    and the ledger rows it caused, then replays."""
    ids: list[str] = []
    with Session(get_engine()) as db:
        calls_before = set(db.exec(select(LlmCall.id)).all())
    yield ids
    with Session(get_engine()) as db:
        if ids:
            # Solves first: `practice_solves.concept_evidence_id` is a foreign key into the
            # rows below it, so evidence cannot be removed while a solve still points at it.
            db.exec(delete(PracticeSolve).where(col(PracticeSolve.problem_id).in_(ids)))
            db.exec(
                delete(ConceptEvidence).where(col(ConceptEvidence.practice_problem_id).in_(ids))
            )
            db.exec(delete(PracticeProblem).where(col(PracticeProblem.id).in_(ids)))
        new = set(db.exec(select(LlmCall.id)).all()) - calls_before
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
        db.commit()
        recompute(db, single_user(db).id)


def client_with(model: Any) -> TestClient:
    use_settings(model_utility=MODEL)
    app.dependency_overrides[get_classifier] = lambda: model
    return sign_in(TestClient(app))


def log(client: TestClient, logged: list[str], **overrides: Any) -> dict[str, Any]:
    body = {
        "title": "Panel painting run lengths",
        "url": "https://example.invalid/p/239",
        "source_site": "leetcode",
    }
    body.update(overrides)
    resp = client.post("/api/v1/practice/problems", json=body)
    assert resp.status_code == 201, resp.text
    logged.append(resp.json()["id"])
    return resp.json()


# --- The gate -------------------------------------------------------------------------------


def test_a_confident_classification_counts_immediately(logged):
    client = client_with(classifier())
    problem = log(client, logged)

    assert problem["status"] == "active"
    assert problem["primary_concept_id"] == PRIMARY
    assert problem["secondary_concept_ids"] == [SECONDARY]
    assert problem["solve_count"] == 1
    assert problem["stability_days"] == practice.INITIAL_INTERVAL_DAYS
    assert problem["due_at"] is not None
    assert [row["concept_id"] for row in problem["evidence"]] == [PRIMARY, SECONDARY]
    assert problem["solves"][0]["concept_evidence_id"] is not None


def test_an_unsure_classification_writes_nothing_and_waits(logged):
    """The gate. Evidence is immutable, so a row written against a guess could never be
    retracted without an amendment mechanism this design does not have — deferring the
    write until a human resolves the tag sidesteps that entirely."""
    client = client_with(classifier(confidence=0.4))
    problem = log(client, logged)

    assert problem["status"] == "pending_classification"
    assert problem["evidence"] == []
    # And it carries no schedule: a due date on something that feeds nothing is a prompt to
    # re-solve a problem the system could not record you having re-solved.
    assert problem["due_at"] is None and problem["stability_days"] is None
    # The proposal is still shown, because correcting one beats retyping it.
    assert problem["primary_concept_id"] == PRIMARY
    assert problem["classification"]["auto_accepted"] is False


def test_a_provider_that_is_down_does_not_lose_the_entry(logged):
    """A logged solve is something the person did. Losing it because a provider hiccuped
    would cost the record; landing it in the state a human already resolves costs a
    confirmation."""
    client = client_with(DeadProvider())
    problem = log(client, logged)

    assert problem["status"] == "pending_classification"
    assert problem["primary_concept_id"] is None
    assert problem["evidence"] == []


def test_confirming_a_classification_writes_the_evidence_that_waited(logged):
    client = client_with(classifier(confidence=0.4))
    problem = log(client, logged)

    resolved = client.patch(
        f"/api/v1/practice/problems/{problem['id']}/classification",
        json={"primary_concept_id": "two-pointers", "secondary_concept_ids": ["sliding-window"]},
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "active"
    assert body["primary_concept_id"] == "two-pointers"
    assert [row["concept_id"] for row in body["evidence"]] == ["two-pointers", "sliding-window"]
    # Scheduled from when it was solved, not from when it was confirmed.
    assert body["stability_days"] == practice.INITIAL_INTERVAL_DAYS


def test_a_classification_already_acted_on_cannot_be_rewritten(logged):
    """409 rather than a correction, and the reason is in the message: the evidence is
    already written and evidence is immutable."""
    client = client_with(classifier())
    problem = log(client, logged)
    resp = client.patch(
        f"/api/v1/practice/problems/{problem['id']}/classification",
        json={"primary_concept_id": "two-pointers"},
    )
    assert resp.status_code == 409
    assert "immutable" in resp.json()["detail"]


def test_a_correction_to_a_concept_that_does_not_exist_is_refused(logged):
    client = client_with(classifier(confidence=0.4))
    problem = log(client, logged)
    resp = client.patch(
        f"/api/v1/practice/problems/{problem['id']}/classification",
        json={"primary_concept_id": "vibes"},
    )
    assert resp.status_code == 422


# --- Reviews and the schedule ---------------------------------------------------------------


def review(client: TestClient, problem_id: str, *, success: bool, when: datetime) -> dict[str, Any]:
    resp = client.post(
        f"/api/v1/practice/problems/{problem_id}/reviews",
        json={"is_success": success, "attempted_at": when.isoformat()},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_three_solves_graduate_a_problem_out_of_the_queue(logged):
    client = client_with(classifier())
    problem = log(client, logged)
    now = datetime.now(UTC)

    after_one = review(client, problem["id"], success=True, when=now + timedelta(days=3))
    assert after_one["solve_count"] == 2
    assert after_one["status"] == "active"
    assert after_one["stability_days"] == pytest.approx(
        practice.INITIAL_INTERVAL_DAYS * practice.GROWTH_FACTOR
    )

    after_two = review(client, problem["id"], success=True, when=now + timedelta(days=11))
    assert after_two["solve_count"] == practice.GRADUATION_SOLVES
    assert after_two["status"] == "graduated"
    assert after_two["due_at"] is None and after_two["graduated_at"] is not None

    assert client.get("/api/v1/practice/review-queue").json()["due"] == []
    # A graduated problem is done, and a review of one is a 409 rather than a fourth solve.
    resp = client.post(
        f"/api/v1/practice/problems/{problem['id']}/reviews", json={"is_success": True}
    )
    assert resp.status_code == 409


def test_a_missed_review_shortens_the_interval_without_undoing_the_solve(logged):
    """A failed attempt is not a solve, so the count does not move — which is what makes
    "three solves and it graduates" mean three solves."""
    client = client_with(classifier())
    problem = log(client, logged)
    missed = review(
        client, problem["id"], success=False, when=datetime.now(UTC) + timedelta(days=3)
    )

    assert missed["solve_count"] == 1
    assert missed["status"] == "active"
    assert missed["stability_days"] == pytest.approx(
        practice.INITIAL_INTERVAL_DAYS * practice.LAPSE_SHRINK
    )


def test_a_miss_nudges_the_shared_mastery_rather_than_only_this_problems_schedule(logged):
    """The concrete mechanism docs/PRACTICE_LOG.md asks for: a lapse on a practice problem
    is evidence about the concept, not just a note about this one problem."""
    client = client_with(classifier())
    problem = log(client, logged)
    review(client, problem["id"], success=False, when=datetime.now(UTC) + timedelta(days=3))

    detail = client.get(f"/api/v1/practice/problems/{problem['id']}").json()
    lapse = [row for row in detail["evidence"] if row["score"] == practice.LAPSE_SCORE]
    assert [row["concept_id"] for row in lapse] == [PRIMARY, SECONDARY]
    assert lapse[0]["confidence"] == practice.LAPSE_CONFIDENCE


def test_a_review_of_a_problem_whose_tag_is_unresolved_is_refused(logged):
    """It is not in the queue, so nothing should be prompting a re-solve — and recording one
    would want evidence there is still no concept to write against."""
    client = client_with(classifier(confidence=0.4))
    problem = log(client, logged)
    resp = client.post(
        f"/api/v1/practice/problems/{problem['id']}/reviews", json={"is_success": True}
    )
    assert resp.status_code == 409


def test_the_queue_holds_what_is_due_most_overdue_first(logged):
    client = client_with(classifier())
    old = log(client, logged, title="Solved a fortnight ago")
    recent = log(client, logged, title="Solved yesterday")

    now = datetime.now(UTC)
    with Session(get_engine()) as db:
        for problem_id, due in (
            (old["id"], now - timedelta(days=9)),
            (recent["id"], now + timedelta(days=2)),
        ):
            row = db.get(PracticeProblem, problem_id)
            assert row is not None
            row.due_at = due
            db.add(row)
        db.commit()

    queue = client.get("/api/v1/practice/review-queue").json()["due"]
    assert [row["id"] for row in queue] == [old["id"]]
    assert queue[0]["days_overdue"] >= 9


def test_a_filtered_page_that_matches_nothing_still_says_where_to_continue(logged):
    """The cursor is decided before the concept filter runs. Deciding after, a page whose
    rows all fail the filter reports no cursor — so a client stops believing it has seen
    everything, while matching problems sit further back. A short page is ordinary; a
    truncated list that looks complete is not."""
    first = client_with(classifier(primary=PRIMARY, secondaries=[]))
    wanted = log(first, logged, title="The one being looked for")
    # Two newer problems, neither tagged with what the filter asks for.
    for title in ("Newer one", "Newest one"):
        client = client_with(classifier(primary="hash-map-counting", secondaries=[]))
        log(client, logged, title=title)

    client = client_with(classifier())
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        query = f"?concept_id={PRIMARY}&limit=1" + (f"&cursor={cursor}" if cursor else "")
        body = client.get(f"/api/v1/practice/problems{query}").json()
        seen += [row["id"] for row in body["problems"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert wanted["id"] in seen


# --- The shared engine ----------------------------------------------------------------------


def test_practice_evidence_is_ordinary_evidence_with_no_item_behind_it(logged):
    """`apply_evidence` reads an item-less row as "we do not know how hard this was" and
    scores it against the candidate's own ability rather than inventing a difficulty. The
    CHECK constraint is what keeps the two shapes from blurring."""
    client = client_with(classifier())
    problem = log(client, logged)

    with Session(get_engine()) as db:
        rows = db.exec(
            select(ConceptEvidence).where(col(ConceptEvidence.practice_problem_id) == problem["id"])
        ).all()
        assert rows
        assert all(row.source == practice.SOURCE for row in rows)
        assert all(row.item_id is None and row.session_id is None for row in rows)
        assert all(row.grader_version == practice.SCHEDULER_VERSION for row in rows)

        user_id = single_user(db).id
        mastery = db.get(Mastery, (user_id, PRIMARY))
        assert mastery is not None and mastery.observations >= 1


def test_a_projection_carrying_practice_evidence_still_replays_exactly(logged):
    """The claim everything rests on, with the third producer in the table."""
    client = client_with(classifier())
    problem = log(client, logged)
    review(client, problem["id"], success=False, when=datetime.now(UTC) + timedelta(days=3))

    def projection() -> dict[str, Any]:
        with Session(get_engine()) as db:
            user_id = single_user(db).id
            rows = db.exec(select(Mastery).where(Mastery.user_id == user_id)).all()
            return {row.concept_id: (row.ability, row.observations, row.stability) for row in rows}

    before = projection()
    assert before
    assert client.post("/api/v1/mastery/recompute").status_code == 200
    assert projection() == before


def test_the_classification_call_is_routed_and_billed_as_its_own_job(logged):
    """docs/PRACTICE_LOG.md asked for the routing to be shared with the utility job and the
    ledger to tell them apart. One router entry gives both."""
    model = classifier()
    client = client_with(model)
    log(client, logged)

    # Against the configured utility model rather than a literal. `client_with` calls
    # `use_settings(model_utility=MODEL)`, but that installs a FastAPI dependency override
    # and this path never reads it: the route calls `service.log_problem(...)` with no
    # `settings`, so `llm.complete` resolves `get_settings()` itself and sees `.env`. The
    # pin was decorative and the test passed only while the ambient default matched it.
    #
    # What this test is named for is the *routing* — that classification goes to the
    # utility model and is billed as its own job — and that is what is asserted now,
    # whichever model the utility slot holds.
    assert model.requests[0]["model"] == get_settings().model_utility
    with Session(get_engine()) as db:
        call = db.exec(select(LlmCall).order_by(col(LlmCall.id).desc())).first()
        assert call is not None and call.job == "practice_log_classify"
        # Not tied to an interview: this is the one model call in the system with no session.
        assert call.session_id is None


def test_the_classifier_cannot_tag_the_primary_concept_twice(logged):
    """It would write the same concept from one solve at two confidences, which reads as two
    readings of one problem."""
    client = client_with(classifier(secondaries=[PRIMARY, SECONDARY]))
    problem = log(client, logged)
    assert problem["secondary_concept_ids"] == [SECONDARY]
    assert [row["concept_id"] for row in problem["evidence"]] == [PRIMARY, SECONDARY]


def test_a_classifier_returning_ten_secondaries_writes_four(logged):
    """The cap the response schema can no longer express.

    Not cosmetic: every secondary writes its own immutable `concept_evidence` row, so an
    uncapped list is an uncapped number of permanent facts about your mastery from one
    logged solve. `maxItems` used to say so and was rejected by the provider — this is
    where it is said now.

    A database test rather than a pure one, even though it is checking a slice: `classify`
    goes through `llm.complete`, which reserves a row on the ledger before it calls
    anything. There is no such thing as a model call here that does not touch Postgres —
    which is also why it takes `logged`, whose teardown removes the ledger rows it caused.
    Written without that fixture first, and the leaked rows broke a budget test three files
    away by spending its $0.001 daily ceiling before it started.
    """
    ids = sorted(practice.concept_ids())
    primary, secondaries = ids[0], ids[1:11]
    model = ScriptedModel(
        model_response(
            text_block(
                json.dumps(
                    {
                        "primary_concept_id": primary,
                        "secondary_concept_ids": secondaries,
                        "confidence": 0.9,
                        "reasoning": "test",
                    }
                )
            )
        )
    )
    result = practice.classify(title="t", url="u", client=model, settings=use_settings())
    assert len(result.secondary_concept_ids) == practice.MAX_SECONDARIES
    assert result.secondary_concept_ids == tuple(secondaries[: practice.MAX_SECONDARIES])
