"""The job tracker's flows against a live Postgres, with scripted models.

`test_jobs.py` pins the projection arithmetic and the taxonomy. This drives the routes,
and the cases that matter are the ones where a shortcut would have been invisible:

- an import that runs the **research pass** and one that does not, chosen by the threshold
  rather than by the caller,
- a stage move that **appends** rather than overwrites, so the funnel can still see where
  the application got to after it was rejected,
- a **recompute** that rebuilds the board from the events and changes nothing, which is the
  only evidence that the events really are the source of truth,
- and the **web searches landing on the ledger**, because they are billed per search and
  are the one cost `usage.*_tokens` cannot see.

Anything that calls `llm.complete` is here rather than in the pure file: the call reserves
a ledger row before it reaches a provider, so even a fully scripted model needs a database.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import sign_in, use_settings
from fakes import ScriptedModel, model_response, text_block
from fastapi.testclient import TestClient
from sqlmodel import Session, col, delete, select

from api import jobs
from api.db import get_engine
from api.main import app
from api.models import JobApplication, JobApplicationEvent, LlmCall
from api.routes.jobs import get_job_parser, get_job_researcher
from api.users import single_user

pytestmark = pytest.mark.db


@pytest.fixture
def tracked():
    """Every application a test creates, plus the ledger rows its imports caused."""
    ids: list[str] = []
    with Session(get_engine()) as db:
        calls_before = set(db.exec(select(LlmCall.id)).all())
    yield ids
    with Session(get_engine()) as db:
        # Events first: they hold the foreign key into the applications.
        user = single_user(db)
        mine = list(
            db.exec(select(JobApplication.id).where(JobApplication.user_id == user.id)).all()
        )
        if mine:
            db.exec(
                delete(JobApplicationEvent).where(col(JobApplicationEvent.application_id).in_(mine))
            )
            db.exec(delete(JobApplication).where(col(JobApplication.id).in_(mine)))
        new = set(db.exec(select(LlmCall.id)).all()) - calls_before
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
        db.commit()


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "company": "Aurora Labs",
        "role": "Software Engineer",
        "location": None,
        "url": None,
        "subcategory": "backend",
        "stage": "applied",
        "confidence": 0.9,
        "notes": None,
        "applied_on": None,
    }
    base.update(overrides)
    return base


def parser(rows: list[dict[str, Any]]) -> ScriptedModel:
    return ScriptedModel(model_response(text_block(json.dumps({"applications": rows}))))


def researcher(rows: list[dict[str, Any]], *, searches: int = 0) -> ScriptedModel:
    response = model_response(
        SimpleNamespace(
            type="tool_use", name=jobs.RECORD_TOOL, id="tu_1", input={"applications": rows}
        )
    )
    if searches:
        response.usage.server_tool_use = SimpleNamespace(web_search_requests=searches)
    return ScriptedModel(response)


def _install(parse: ScriptedModel, research: ScriptedModel | None = None) -> None:
    app.dependency_overrides[get_job_parser] = lambda: parse
    app.dependency_overrides[get_job_researcher] = lambda: research


@pytest.fixture
def client(tracked) -> TestClient:
    with TestClient(app) as raw:
        yield sign_in(raw)


# --- Importing ----------------------------------------------------------------------------


def test_a_short_paste_is_parsed_and_not_researched(client):
    """The threshold decides the second call, never the first. Two rows is below it, so
    the research pass is skipped with a reason rather than silently not happening."""
    use_settings(jobs_research_threshold=10)
    _install(
        parser(
            [
                _row(company="Aurora Labs", role="Backend Engineer", subcategory="backend"),
                _row(company="Northwind Systems", role="Trader", subcategory="quant_trading"),
            ]
        )
    )
    response = client.post("/api/v1/jobs/import", json={"text": "Aurora, Northwind"})
    assert response.status_code == 201
    body = response.json()
    assert body["created"] == 2
    assert body["researched"] is False
    assert "threshold" in body["research_skipped"]
    categories = {row["company"]: row["category"] for row in body["applications"]}
    assert categories == {"Aurora Labs": "swe", "Northwind Systems": "quant"}


def test_a_long_paste_is_researched_and_the_searches_reach_the_ledger(client):
    """The whole point of the second pass, and the cost it carries.

    Web search is billed per search on top of the tokens, so a ledger that recorded only
    tokens would report this import at a fraction of what it cost — against dollar
    ceilings that are supposed to be the thing that binds.
    """
    use_settings(jobs_research_threshold=1, model_provider="anthropic", anthropic_api_key="k")
    parsed = [
        _row(company="Aurora Labs", role="Engineer", confidence=0.4),
        _row(company="Northwind Systems", role="Trader", subcategory="quant_trading"),
    ]
    enriched = [
        _row(company="Aurora Labs", role="Software Engineer, Platform", location="Boston"),
        _row(company="Northwind Systems", role="Quantitative Trader", subcategory="quant_trading"),
    ]
    _install(parser(parsed), researcher(enriched, searches=4))

    body = client.post("/api/v1/jobs/import", json={"text": "a long list"}).json()
    assert body["researched"] is True
    assert body["research_skipped"] is None
    assert body["web_searches"] == 4
    roles = {row["company"]: row["role"] for row in body["applications"]}
    assert roles["Aurora Labs"] == "Software Engineer, Platform"

    with Session(get_engine()) as db:
        searched = db.exec(
            select(LlmCall)
            .where(LlmCall.job == "job_research")
            .order_by(col(LlmCall.created_at).desc())
        ).first()
    assert searched is not None
    assert searched.web_search_requests == 4
    # $10 per 1,000 searches, and the row is priced with them included.
    assert searched.cost_usd >= 4 * 0.01


def test_research_that_fails_still_imports_the_parsed_rows(client):
    """The contract of the research pass: it is an enrichment over rows that already
    exist, so a provider that is down costs a bit of detail and nothing else."""
    use_settings(jobs_research_threshold=0, model_provider="bedrock")
    _install(parser([_row(company="Aurora Labs", role="Engineer")]))
    body = client.post("/api/v1/jobs/import", json={"text": "Aurora"}).json()
    assert body["created"] == 1
    assert body["researched"] is False
    assert "Bedrock" in body["research_skipped"]


def test_re_pasting_the_same_list_adds_nothing(client):
    """Re-pasting is the normal way this gets used, and the alternative to idempotence is
    a board that quietly doubles every time somebody updates their spreadsheet."""
    use_settings(jobs_research_threshold=10)
    rows = [_row(company="Aurora Labs", role="Backend Engineer")]
    _install(parser(rows))
    assert client.post("/api/v1/jobs/import", json={"text": "Aurora"}).json()["created"] == 1
    _install(parser(rows))
    again = client.post("/api/v1/jobs/import", json={"text": "Aurora"}).json()
    assert again["created"] == 0
    assert again["duplicates"] == 1


def test_a_low_confidence_tag_is_flagged_but_still_tracked(client):
    """Unlike the practice log's gate, this one holds nothing back — an application writes
    no evidence, so a doubtful tag mis-colours a chart and cannot do worse."""
    use_settings(jobs_research_threshold=10)
    _install(parser([_row(company="Aurora Labs", role="Engineer", confidence=0.2)]))
    (row,) = client.post("/api/v1/jobs/import", json={"text": "Aurora"}).json()["applications"]
    assert row["status"] == "pending_classification"
    assert row["current_stage"] == "applied"


def test_a_paste_the_parser_finds_nothing_in_is_a_422(client):
    use_settings(jobs_research_threshold=10)
    _install(parser([]))
    response = client.post("/api/v1/jobs/import", json={"text": "lunch tomorrow?"})
    assert response.status_code == 422


# --- Stages -------------------------------------------------------------------------------


def _one(client, **overrides: Any) -> dict[str, Any]:
    body = {"company": "Aurora Labs", "role": "Software Engineer", "subcategory": "backend"}
    body.update(overrides)
    response = client.post("/api/v1/jobs", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_new_application_starts_with_an_applied_event(client):
    created = _one(client)
    assert created["current_stage"] == "applied"
    assert [event["stage"] for event in created["events"]] == ["applied"]


def test_an_imported_row_already_past_applied_still_passes_through_it(client):
    """The funnel counts a pipeline that reached the second round as having reached the
    first. The events are the only place that can be true, so the `applied` event is
    written even when the row arrives at `final`."""
    created = _one(client, stage="final")
    assert [event["stage"] for event in created["events"]] == ["applied", "final"]
    assert created["furthest_stage"] == "final"


def test_a_stage_move_appends_and_a_rejection_keeps_the_high_water_mark(client):
    created = _one(client)
    for stage in ("oa", "round_1", "final", "rejected"):
        response = client.post(f"/api/v1/jobs/{created['id']}/stage", json={"stage": stage})
        assert response.status_code == 201, response.text
    detail = response.json()
    assert [event["stage"] for event in detail["events"]] == [
        "applied",
        "oa",
        "round_1",
        "final",
        "rejected",
    ]
    assert detail["current_stage"] == "rejected"
    assert detail["furthest_stage"] == "final"
    assert detail["outcome"] == "rejected"


def test_moving_to_the_stage_it_is_already_in_is_a_no_op(client):
    """A double-click must not put two identical rows in a history whose whole purpose is
    to be read as a sequence of things that actually happened."""
    created = _one(client)
    client.post(f"/api/v1/jobs/{created['id']}/stage", json={"stage": "oa"})
    detail = client.post(f"/api/v1/jobs/{created['id']}/stage", json={"stage": "oa"}).json()
    assert [event["stage"] for event in detail["events"]] == ["applied", "oa"]


def test_an_unknown_stage_is_refused(client):
    """400, not 422, and the distinction is docs/API.md's: a body that does not match the
    schema is malformed, and only a well-formed body whose *meaning* is wrong is 422.
    `stage` is a `Literal`, so an unknown one never reaches the route's own check."""
    created = _one(client)
    response = client.post(f"/api/v1/jobs/{created['id']}/stage", json={"stage": "vibes"})
    assert response.status_code == 400
    assert response.json()["type"].endswith("malformed-request")


def test_recompute_rebuilds_the_board_and_changes_nothing(client):
    """The proof that the projection is derived. Corrupt the cached columns, replay, and
    they come back — which is only possible if the events are what they are computed from."""
    created = _one(client)
    client.post(f"/api/v1/jobs/{created['id']}/stage", json={"stage": "final"})

    with Session(get_engine()) as db:
        row = db.get(JobApplication, created["id"])
        row.current_stage = "applied"
        row.furthest_stage = "applied"
        row.outcome = "withdrawn"
        db.add(row)
        db.commit()

    replay = client.post("/api/v1/jobs/recompute").json()
    # Both numbers, because they answer different questions: one row was corrupted, so
    # exactly one should come back corrected — a replay that reports every row as
    # "recomputed" cannot tell you whether the board was lying.
    assert replay["replayed"] >= 1
    assert replay["corrected"] == 1
    detail = client.get(f"/api/v1/jobs/{created['id']}").json()
    assert detail["current_stage"] == "final"
    assert detail["furthest_stage"] == "final"
    assert detail["outcome"] == "open"

    # And a second replay corrects nothing, which is the assertion that the projection is
    # a fixed point rather than merely reachable once.
    assert client.post("/api/v1/jobs/recompute").json()["corrected"] == 0


# --- Classification and stats -------------------------------------------------------------


def test_confirming_a_tag_derives_the_big_category(client):
    """The category is never sent and never stored independently, so an inconsistent pair
    — `quant` + `frontend` — is unrepresentable rather than merely unlikely."""
    created = _one(client, subcategory=None)
    assert created["status"] == "pending_classification"
    detail = client.patch(
        f"/api/v1/jobs/{created['id']}/classification", json={"subcategory": "quant_research"}
    ).json()
    assert detail["category"] == "quant"
    assert detail["status"] == "tracked"
    assert detail["classification_confidence"] == 1.0


def test_the_funnel_counts_where_applications_reached_not_where_they_are(client):
    """Two applications: one rejected after an onsite, one still at the OA. Counted off
    `current_stage` the onsite would have vanished from every bucket above `applied`."""
    use_settings(jobs_research_threshold=10)
    far = _one(client, company="Aurora Labs", role="Engineer")
    near = _one(client, company="Northwind Systems", role="Trader", subcategory="quant_trading")
    for stage in ("oa", "round_1", "final", "rejected"):
        client.post(f"/api/v1/jobs/{far['id']}/stage", json={"stage": stage})
    client.post(f"/api/v1/jobs/{near['id']}/stage", json={"stage": "oa"})

    stats = client.get("/api/v1/jobs/stats").json()
    reached = {row["stage"]: row["reached"] for row in stats["funnel"]}
    assert reached["applied"] == 2
    assert reached["oa"] == 2
    assert reached["final"] == 1
    assert reached["offer"] == 0
    assert stats["response_rate"] == 1.0
    assert stats["by_category"]["swe"]["total"] == 1
    assert stats["by_category"]["quant"]["subcategories"] == {"quant_trading": 1}


def test_stats_on_an_empty_board_does_not_divide_by_zero(client):
    stats = client.get("/api/v1/jobs/stats").json()
    assert stats["total"] == 0
    assert stats["response_rate"] == 0.0
    assert all(row["conversion"] == 0.0 for row in stats["funnel"])


def test_the_catalog_is_served_rather_than_duplicated_in_the_client(client):
    """The enum the model is constrained to and the buttons a person clicks have to be one
    list, and this is the endpoint that makes them one."""
    catalog = client.get("/api/v1/jobs/catalog").json()
    assert catalog["ladder"] == list(jobs.LADDER)
    assert set(catalog["categories"]) == set(jobs.CATALOG)


def test_deleting_an_application_takes_its_history_with_it(client):
    created = _one(client)
    client.post(f"/api/v1/jobs/{created['id']}/stage", json={"stage": "oa"})
    assert client.delete(f"/api/v1/jobs/{created['id']}").status_code == 204
    assert client.get(f"/api/v1/jobs/{created['id']}").status_code == 404
    with Session(get_engine()) as db:
        left = db.exec(
            select(JobApplicationEvent).where(JobApplicationEvent.application_id == created["id"])
        ).all()
    assert not left


def test_every_jobs_route_needs_a_session_cookie():
    """The prefix carries the dependency, so this is really a test that the router was
    mounted under it rather than beside it."""
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/jobs").status_code == 401
        assert anonymous.get("/api/v1/jobs/stats").status_code == 401
        assert anonymous.post("/api/v1/jobs/import", json={"text": "x"}).status_code == 401


# --- What the optimisation must keep true -------------------------------------------------


def _statements(db_engine) -> tuple[list[str], object]:
    """Record every SQL statement issued while the returned handle is installed."""
    from sqlalchemy import event

    seen: list[str] = []

    def before(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db_engine, "before_cursor_execute", before)
    return seen, before


def test_an_import_does_not_query_once_per_row(client):
    """The duplicate check is one query for the whole paste, not one per row.

    Pinned with a number because this is the kind of thing that regresses the moment
    somebody moves the check back inside the loop, and nothing else would notice: the
    behaviour stays correct and only the cost changes. Measured before the fix: importing
    40 rows issued 240 statements, 80 of them this lookup. It now issues a constant few,
    and the assertion is deliberately loose about the constant and strict about the shape.
    """
    from sqlalchemy import event

    use_settings(jobs_research_threshold=100)
    rows = [_row(company=f"Bench {i:03d}", role="Engineer") for i in range(30)]
    _install(parser(rows))

    engine = get_engine()
    seen, handle = _statements(engine)
    try:
        response = client.post("/api/v1/jobs/import", json={"text": "thirty companies"})
    finally:
        event.remove(engine, "before_cursor_execute", handle)

    assert response.json()["created"] == 30
    selects = [s for s in seen if s.lstrip().upper().startswith("SELECT")]
    lookups = [s for s in selects if "job_applications" in s]
    # Well under one per row: the whole import reads the existing set once, and the route
    # then reads the board back to return it.
    assert len(lookups) <= 5, f"{len(lookups)} lookups for 30 rows — the check is back in the loop"


def test_a_paste_naming_the_same_job_twice_adds_it_once(client):
    """Within a single paste, not just against what is already stored.

    A per-row database check could not catch this: neither row is committed while the
    import is running, so both would look new. The in-memory index is what sees it.
    """
    use_settings(jobs_research_threshold=100)
    _install(
        parser(
            [
                _row(company="Aurora Labs", role="Backend Engineer"),
                _row(company="Aurora Labs", role="Backend Engineer"),
                _row(company="Northwind Systems", role="Trader", subcategory="quant_trading"),
            ]
        )
    )
    body = client.post("/api/v1/jobs/import", json={"text": "a list with a repeat"}).json()
    assert body["created"] == 2
    assert body["duplicates"] == 1


def test_deduplication_ignores_case_and_surrounding_space(client):
    """The unique index folds case, and so does the check — they used to disagree.

    While they disagreed, "Aurora Labs" and "aurora labs" were two rows to the constraint
    and one row to every duplicate check, so the second was storable and then permanently
    invisible to the code meant to find it.
    """
    use_settings(jobs_research_threshold=100)
    _install(parser([_row(company="Aurora Labs", role="Backend Engineer")]))
    assert client.post("/api/v1/jobs/import", json={"text": "x"}).json()["created"] == 1

    _install(parser([_row(company="  aurora labs  ", role="BACKEND ENGINEER")]))
    again = client.post("/api/v1/jobs/import", json={"text": "x"}).json()
    assert again["created"] == 0
    assert again["duplicates"] == 1


def test_an_imported_row_is_written_with_its_projection_already_correct(client):
    """`insert_application` computes the projection in memory instead of re-reading the
    rows it just wrote. This asserts the shortcut lands on the same answer `recompute`
    would: a replay immediately afterwards corrects nothing."""
    use_settings(jobs_research_threshold=100)
    _install(
        parser(
            [
                _row(company="Aurora Labs", role="Engineer", stage="final"),
                _row(company="Northwind Systems", role="Trader", stage="rejected"),
                _row(company="Helio Robotics", role="ML Engineer", stage="applied"),
            ]
        )
    )
    body = client.post("/api/v1/jobs/import", json={"text": "three"}).json()
    assert body["created"] == 3

    replay = client.post("/api/v1/jobs/recompute").json()
    assert replay["replayed"] == 3
    assert replay["corrected"] == 0, "the in-memory projection disagrees with a replay"

    rows = {row["company"]: row for row in body["applications"]}
    assert rows["Aurora Labs"]["furthest_stage"] == "final"
    assert rows["Northwind Systems"]["furthest_stage"] == "applied"
    assert rows["Northwind Systems"]["outcome"] == "rejected"
