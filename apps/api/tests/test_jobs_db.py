"""The job tracker's flows against a live Postgres, with scripted models.

`test_jobs.py` pins the projection arithmetic and the taxonomy. This drives the routes,
and the cases that matter are the ones where a shortcut would have been invisible:

- an import that runs the **research pass** and one that does not, chosen by what each new
  row is missing rather than by the caller or the length of the list,
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
import os
from collections.abc import Iterator
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
from api.models import JobApplication, JobApplicationEvent, LlmCall, User
from api.routes.jobs import get_job_parser, get_job_researcher

pytestmark = pytest.mark.db


@pytest.fixture
def user_id() -> Iterator[str]:
    """A user of this test file's own, and the reason every assertion here is safe.

    The board, the funnel and the totals are all **per user**, so a test that signs in as
    its own user is measuring only the rows it made. Written against the shared local user
    first, and that was wrong twice over: the teardown deleted applications somebody had
    really imported, and the assertions — `reached["applied"] == 2` and friends — only held
    while the board happened to be empty. Both stop being true the first time this database
    holds real data, which is exactly when a false failure is most expensive.

    `users.github_id` is unique, so the id is random and negative: negative to stay clear of
    any real GitHub account, random so two tests never collide. Three bytes, not four —
    the column is a 32-bit `INTEGER` and a four-byte negative overflows it.
    """
    github_id = -int.from_bytes(os.urandom(3), "big") - 1
    with Session(get_engine()) as db:
        user = User(github_id=github_id)
        db.add(user)
        db.commit()
        uid = user.id
    yield uid
    with Session(get_engine()) as db:
        mine = list(db.exec(select(JobApplication.id).where(JobApplication.user_id == uid)).all())
        if mine:
            # Events first: they hold the foreign key into the applications.
            db.exec(
                delete(JobApplicationEvent).where(col(JobApplicationEvent.application_id).in_(mine))
            )
            db.exec(delete(JobApplication).where(col(JobApplication.id).in_(mine)))
        db.exec(delete(User).where(col(User.id) == uid))
        db.commit()


@pytest.fixture
def ledger() -> Iterator[None]:
    """Remove the `llm_calls` rows these tests cause, by difference against a snapshot.

    Not scoped by user — the ledger has no user column — so it has to be a difference.
    Leaving them behind is not cosmetic: they are priced at real rates, and a budget test
    three files away sets a $0.001 daily ceiling that a few stray rows will spend.
    """
    with Session(get_engine()) as db:
        before = set(db.exec(select(LlmCall.id)).all())
    yield
    with Session(get_engine()) as db:
        new = list(set(db.exec(select(LlmCall.id)).all()) - before)
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
def client(user_id: str, ledger: None) -> Iterator[TestClient]:
    """Signed in as this test's own user, so the board it sees is the board it made."""
    with TestClient(app) as raw:
        yield sign_in(raw, user_id)


# --- Importing ----------------------------------------------------------------------------


RESEARCHING = {"model_provider": "anthropic", "anthropic_api_key": "k"}
# The research pass switched off. Every import test that is not *about* research uses it,
# because the settings under test are the real ones — `.env` may name the Anthropic
# provider and a real key — and a research pass with no scripted client builds a real one.
NO_RESEARCH = {"jobs_research_max_searches": 0}

COMPLETE = {"location": "Boston", "url": "https://jobs.example.com/1", "confidence": 0.9}


def test_complete_rows_are_parsed_and_not_researched(client):
    """What a row is missing decides the second call, never the first — and not the length
    of the list. Two rows that already carry a URL, a location and a confident tag give the
    research pass nothing to do, so it is not called, and the import says why."""
    use_settings(**RESEARCHING)
    unused = researcher([])
    _install(
        parser(
            [
                _row(company="Aurora Labs", role="Backend Engineer", **COMPLETE),
                _row(
                    company="Northwind Systems",
                    role="Trader",
                    subcategory="quant_trading",
                    **COMPLETE,
                ),
            ]
        ),
        unused,
    )
    response = client.post("/api/v1/jobs/import", json={"text": "Aurora, Northwind"})
    assert response.status_code == 201
    body = response.json()
    assert body["created"] == 2
    assert body["researched"] is False
    assert body["researched_rows"] == 0
    assert "already has a URL" in body["research_skipped"]
    assert unused.requests == []
    categories = {row["company"]: row["category"] for row in body["applications"]}
    assert categories == {"Aurora Labs": "swe", "Northwind Systems": "quant"}


def test_a_short_paste_missing_detail_is_researched_and_the_searches_reach_the_ledger(client):
    """The whole point of the second pass, and the cost it carries.

    Three rows — the old threshold of ten would never have looked at them. Two are missing
    something and are sent; the third is complete and is not, so it stays exactly as pasted
    and is marked `paste` rather than `paste+research`.

    Web search is billed per search on top of the tokens, so a ledger that recorded only
    tokens would report this import at a fraction of what it cost — against dollar
    ceilings that are supposed to be the thing that binds.
    """
    use_settings(**RESEARCHING)
    parsed = [
        _row(company="Aurora Labs", role="Engineer", confidence=0.4),
        _row(company="Cascade Analytics", role="Analyst", subcategory="data_science", **COMPLETE),
        _row(company="Northwind Systems", role="Trader", subcategory="quant_trading"),
    ]
    enriched = [
        _row(company="Aurora Labs", role="Software Engineer, Platform", location="Boston"),
        _row(company="Northwind Systems", role="Quantitative Trader", subcategory="quant_trading"),
    ]
    scripted = researcher(enriched, searches=4)
    _install(parser(parsed), scripted)

    body = client.post("/api/v1/jobs/import", json={"text": "a short list"}).json()
    assert body["researched"] is True
    assert body["research_skipped"] is None
    assert body["researched_rows"] == 2
    assert body["web_searches"] == 4
    rows = {row["company"]: row for row in body["applications"]}
    assert rows["Aurora Labs"]["role"] == "Software Engineer, Platform"
    assert rows["Aurora Labs"]["source"] == "paste+research"
    assert rows["Northwind Systems"]["source"] == "paste+research"
    assert rows["Cascade Analytics"]["source"] == "paste"
    assert rows["Cascade Analytics"]["url"] == "https://jobs.example.com/1"

    # Only the two incomplete rows reached the model.
    (request,) = scripted.requests
    prompt = request["messages"][0]["content"]
    assert "Aurora Labs" in prompt and "Northwind Systems" in prompt
    assert "Cascade Analytics" not in prompt

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


def test_rows_already_tracked_are_never_researched(client):
    """Re-pasting a list is the normal way this is used. Researching a row only to discard
    it as a duplicate would pay for Opus and the searches and keep nothing, so the
    duplicate check runs before the research pass rather than after it."""
    use_settings(**NO_RESEARCH)
    _install(parser([_row(company="Aurora Labs", role="Backend Engineer")]))
    assert client.post("/api/v1/jobs/import", json={"text": "Aurora"}).json()["created"] == 1

    use_settings(**RESEARCHING)
    unused = researcher([])
    _install(parser([_row(company="Aurora Labs", role="Backend Engineer")]), unused)
    again = client.post("/api/v1/jobs/import", json={"text": "Aurora"}).json()
    assert again["created"] == 0
    assert again["duplicates"] == 1
    assert again["researched"] is False
    assert again["research_skipped"] == "every row is already tracked"
    assert unused.requests == []


def test_a_zero_search_ceiling_switches_the_research_pass_off(client):
    """The off switch, now that no threshold can be set high enough to mean "never"."""
    use_settings(**RESEARCHING, **NO_RESEARCH)
    unused = researcher([])
    _install(parser([_row(company="Aurora Labs", role="Engineer")]), unused)
    body = client.post("/api/v1/jobs/import", json={"text": "Aurora"}).json()
    assert body["created"] == 1
    assert body["researched"] is False
    assert "JOBS_RESEARCH_MAX_SEARCHES=0" in body["research_skipped"]
    assert unused.requests == []


def test_research_that_fails_still_imports_the_parsed_rows(client):
    """The contract of the research pass: it is an enrichment over rows that already
    exist, so a provider that is down costs a bit of detail and nothing else."""
    use_settings(model_provider="bedrock")
    _install(parser([_row(company="Aurora Labs", role="Engineer")]))
    body = client.post("/api/v1/jobs/import", json={"text": "Aurora"}).json()
    assert body["created"] == 1
    assert body["researched"] is False
    assert "Bedrock" in body["research_skipped"]


def test_re_pasting_the_same_list_adds_nothing(client):
    """Re-pasting is the normal way this gets used, and the alternative to idempotence is
    a board that quietly doubles every time somebody updates their spreadsheet."""
    use_settings(**NO_RESEARCH)
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
    use_settings(**NO_RESEARCH)
    _install(parser([_row(company="Aurora Labs", role="Engineer", confidence=0.2)]))
    (row,) = client.post("/api/v1/jobs/import", json={"text": "Aurora"}).json()["applications"]
    assert row["status"] == "pending_classification"
    assert row["current_stage"] == "applied"


def test_a_paste_the_parser_finds_nothing_in_is_a_422(client):
    use_settings(**NO_RESEARCH)
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
    use_settings(**NO_RESEARCH)
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
    assert stats["rejections"] == {
        "total": 0,
        "rate": 0.0,
        "after_stage": [
            {"stage": row["stage"], "label": row["label"], "count": 0, "share": 0.0}
            for row in stats["funnel"]
        ],
        "median_days_to_rejection": None,
        "recent": [],
    }
    assert stats["time_in_stage"]["longest_waiting"] == []
    assert all(
        row["left"] == 0 and row["waiting"] == 0 and row["median_days"] is None
        for row in stats["time_in_stage"]["stages"]
    )


def test_rejections_are_tracked_by_the_rung_they_came_after(client):
    """Three applications: one rejected after a final round, one rejected straight from
    `applied`, one still open. The tracker files each rejection under the rung it was
    rejected *after* — `furthest_stage`, as the funnel counts — and lists the newest first,
    with the days between applying and the rejection event."""
    use_settings(**NO_RESEARCH)
    onsite = _one(client, company="Aurora Labs", role="Engineer", applied_at="2026-06-01T00:00:00Z")
    cold = _one(client, company="Northwind Systems", role="Trader", subcategory="quant_trading")
    _one(client, company="Cascade Analytics", role="Analyst")
    for stage in ("oa", "round_1", "final"):
        client.post(f"/api/v1/jobs/{onsite['id']}/stage", json={"stage": stage})
    client.post(
        f"/api/v1/jobs/{onsite['id']}/stage",
        json={"stage": "rejected", "occurred_at": "2026-06-29T12:00:00Z"},
    )
    client.post(f"/api/v1/jobs/{cold['id']}/stage", json={"stage": "rejected"})

    rejections = client.get("/api/v1/jobs/stats").json()["rejections"]
    assert rejections["total"] == 2
    assert rejections["rate"] == 2 / 3
    after = {row["stage"]: row["count"] for row in rejections["after_stage"]}
    assert after == {
        "applied": 1,
        "oa": 0,
        "video_assessment": 0,
        "phone_screen": 0,
        "round_1": 0,
        "round_2": 0,
        "final": 1,
        "offer": 0,
    }
    shares = {row["stage"]: row["share"] for row in rejections["after_stage"]}
    assert shares["final"] == 0.5

    recent = rejections["recent"]
    assert [row["company"] for row in recent] == ["Northwind Systems", "Aurora Labs"]
    assert recent[1]["furthest_stage_label"] == "Final / onsite"
    assert recent[1]["days_after_applying"] == 28
    assert recent[0]["days_after_applying"] == 0
    assert rejections["median_days_to_rejection"] == 14.0


def test_a_second_rejection_event_is_the_one_that_counts(client):
    """A row moved to rejected, reopened, and rejected again dates from the later event —
    the one the person meant — and is still one rejection, not two."""
    row = _one(client, applied_at="2026-06-01T00:00:00Z")
    client.post(
        f"/api/v1/jobs/{row['id']}/stage",
        json={"stage": "rejected", "occurred_at": "2026-06-03T00:00:00Z"},
    )
    client.post(f"/api/v1/jobs/{row['id']}/stage", json={"stage": "phone_screen"})
    client.post(
        f"/api/v1/jobs/{row['id']}/stage",
        json={"stage": "rejected", "occurred_at": "2026-06-11T00:00:00Z"},
    )

    rejections = client.get("/api/v1/jobs/stats").json()["rejections"]
    assert rejections["total"] == 1
    assert rejections["recent"][0]["days_after_applying"] == 10
    assert rejections["recent"][0]["furthest_stage"] == "phone_screen"


def test_time_in_stage_is_read_off_the_events_the_board_writes(client):
    """Through the route, against real timestamps. One application moved through the OA
    and rejected after a phone screen; one still sitting at `applied`. The moves are
    backdated by `occurred_at`, so the stints are exact; the waiting row is measured
    against the real clock, so only its rung and its presence are pinned."""
    far = _one(client, company="Aurora Labs", role="Engineer", applied_at="2026-06-01T00:00:00Z")
    _one(client, company="Northwind Systems", role="Trader", subcategory="quant_trading")
    for stage, when in (
        ("oa", "2026-06-05T00:00:00Z"),
        ("phone_screen", "2026-06-12T00:00:00Z"),
        ("rejected", "2026-06-20T00:00:00Z"),
    ):
        client.post(f"/api/v1/jobs/{far['id']}/stage", json={"stage": stage, "occurred_at": when})

    report = client.get("/api/v1/jobs/stats").json()["time_in_stage"]
    stages = {row["stage"]: row for row in report["stages"]}
    assert (stages["applied"]["left"], stages["applied"]["median_days"]) == (1, 4.0)
    assert (stages["oa"]["left"], stages["oa"]["median_days"]) == (1, 7.0)
    assert (stages["phone_screen"]["left"], stages["phone_screen"]["median_days"]) == (1, 8.0)
    assert stages["applied"]["waiting"] == 1
    (waiting,) = report["longest_waiting"]
    assert (waiting["company"], waiting["stage"]) == ("Northwind Systems", "applied")


def test_a_row_imported_mid_ladder_is_not_timed_on_the_way_in(client):
    """An import at `final` writes the `final` event at the moment of the import. Timing
    the applied -> final gap would report "how long until I pasted the list" as time on a
    rung, so nothing is recorded as having left `applied`."""
    use_settings(**NO_RESEARCH)
    _install(
        parser(
            [_row(company="Aurora Labs", role="Engineer", stage="final", applied_on="2026-05-01")]
        )
    )
    client.post("/api/v1/jobs/import", json={"text": "Aurora, onsite done"})
    report = client.get("/api/v1/jobs/stats").json()["time_in_stage"]
    stages = {row["stage"]: row for row in report["stages"]}
    assert stages["applied"]["left"] == 0
    assert stages["final"]["waiting"] == 1
    assert report["longest_waiting"][0]["days"] == 0


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
    mounted under it rather than beside it.

    `use_settings()` is what makes 401 the thing being tested. Without it the app has no
    `SESSION_SECRET` and every `/api/v1` route answers `503 not-configured` instead —
    correct, deliberate, and a different assertion. Written without it, this passed locally
    against a `.env` that has a secret and failed in CI, which builds its environment from
    nothing. `test_corpus_routes_db.py` carries the same note about the same mistake, which
    is how this one was diagnosed.
    """
    use_settings()
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

    use_settings(**NO_RESEARCH)
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
    use_settings(**NO_RESEARCH)
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
    use_settings(**NO_RESEARCH)
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
    use_settings(**NO_RESEARCH)
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
