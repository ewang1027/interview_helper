"""The job tracker's projection, taxonomy and model plumbing — no database.

The database tests exercise the flows. These pin the three things that are logic rather
than wiring, and each is here because it is the part that would be wrong quietly:

- the **projection**, because `furthest_stage` is what every conversion rate is computed
  from and a rejection must not erase the rounds that came before it,
- the **taxonomy**, because the model is constrained to an enum built from it and a
  duplicated sub-category would silently make one big category unreachable,
- the **one research path that is pure**, the provider check, because it is the thing that
  decides whether the expensive call happens at all.

Everything else about the research pass runs through `llm.complete`, which reserves a row
on the ledger before it calls anything — so those tests need Postgres and live in
`test_jobs_db.py` beside the flows.
"""

from __future__ import annotations

from datetime import UTC, datetime

from api import jobs
from api.models import JobApplicationEvent
from api.settings import Settings


def _event(sequence: int, stage: str) -> JobApplicationEvent:
    return JobApplicationEvent(
        application_id="a1",
        sequence=sequence,
        stage=stage,
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _settings(**changes: object) -> Settings:
    base = Settings(
        model_provider="anthropic",
        # Short on purpose: scripts/secret_scan.sh treats 12+ characters after an
        # ANTHROPIC_API_KEY assignment as a possible real key, and it is right to.
        anthropic_api_key="test",
        session_secret="tests-only",
    )
    return base.model_copy(update=changes)


# --- The projection ---------------------------------------------------------------------


def test_no_events_projects_to_applied():
    assert jobs.project([]) == ("applied", "applied", "open")


def test_the_projection_follows_the_last_event():
    events = [_event(0, "applied"), _event(1, "oa"), _event(2, "round_1")]
    assert jobs.project(events) == ("round_1", "round_1", "open")


def test_a_rejection_keeps_the_furthest_stage_it_reached():
    """The whole reason `furthest_stage` is a separate column.

    Counted off `current_stage`, this application would leave the "reached a final round"
    bucket the moment the rejection arrived — so the funnel would get *better* every time
    something went badly, which is precisely backwards.
    """
    events = [_event(0, "applied"), _event(1, "oa"), _event(2, "final"), _event(3, "rejected")]
    current, furthest, outcome = jobs.project(events)
    assert current == "rejected"
    assert furthest == "final"
    assert outcome == "rejected"


def test_stages_arriving_out_of_order_do_not_move_you_backwards():
    """A recruiter screen booked after the online assessment is a scheduling quirk, not a
    demotion. `furthest` is a maximum over the ladder, never the last thing seen."""
    events = [_event(0, "applied"), _event(1, "round_1"), _event(2, "phone_screen")]
    _, furthest, _ = jobs.project(events)
    assert furthest == "round_1"


def test_terminal_stages_are_not_ranked():
    """`withdrawn` is a way a pipeline ends, not a place in it. If it had a rank, every
    withdrawal would land somewhere in the funnel and be counted as progress."""
    for stage in jobs.TERMINAL:
        assert stage not in jobs.RANK
    events = [_event(0, "applied"), _event(1, "withdrawn")]
    assert jobs.project(events) == ("withdrawn", "applied", "withdrawn")


def test_an_offer_is_both_a_stage_and_an_outcome():
    events = [_event(0, "applied"), _event(1, "final"), _event(2, "offer")]
    assert jobs.project(events) == ("offer", "offer", "offer")


# --- The taxonomy -----------------------------------------------------------------------


def test_subcategories_are_globally_unique():
    """Load-bearing. The model picks a sub-category and the big category is *derived* from
    it, so a name appearing under two categories would make the mapping ambiguous and one
    of those categories unreachable — silently, and only for that one role type."""
    flat = [sub for subs in jobs.CATALOG.values() for sub in subs]
    assert len(flat) == len(set(flat))
    assert len(jobs.CATEGORY_FOR_SUBCATEGORY) == len(flat)


def test_the_three_categories_the_tracker_exists_for_are_present():
    assert {"swe", "ai", "quant"} <= set(jobs.CATALOG)


def test_the_row_schema_enumerates_the_taxonomy_and_the_ladder():
    """Same reason the practice log enumerates concept ids: a tag that is not in the
    taxonomy cannot be expressed, rather than having to be caught after the fact."""
    schema = jobs.row_schema()
    assert schema["properties"]["subcategory"]["enum"] == list(jobs.SUBCATEGORIES)
    assert schema["properties"]["stage"]["enum"] == list(jobs.STAGES)
    assert schema["additionalProperties"] is False


def test_the_record_tool_is_strict():
    """Strict tool use is what makes the research pass's output validated rather than
    parsed. Without it the loop is reading whatever the model felt like emitting."""
    tool = jobs.record_tool()
    assert tool["strict"] is True
    assert tool["input_schema"]["additionalProperties"] is False


def test_the_search_tool_carries_its_own_ceiling():
    """`max_uses` is the limit that binds, because searches are billed per search and the
    provider is the one counting. A check after the call is a check after the money."""
    tool = jobs.search_tool(7)
    assert tool["type"] == "web_search_20260209"
    assert tool["max_uses"] == 7


# --- The research pass's one pure path ---------------------------------------------------


def test_research_is_refused_on_bedrock_before_it_costs_anything():
    """The one hard provider constraint in the module. Web search does not exist on
    Bedrock, so this can never work there — and finding that out as a 400 halfway through
    an import would be a worse way to learn it than a sentence saying so.

    Pure because it is checked *before* the call: no ledger row, no provider, no database.
    Every other research path goes through `llm.complete` and is tested in
    `test_jobs_db.py`."""
    reason = jobs.research_available(_settings(model_provider="bedrock"))
    assert reason is not None and "Bedrock" in reason


def test_research_needs_a_key_when_the_provider_is_anthropic():
    assert jobs.research_available(_settings(anthropic_api_key=None)) is not None
    assert jobs.research_available(_settings()) is None


def test_research_with_no_rows_does_not_call_anything():
    """A client that would raise if touched, so this proves the early return rather than
    merely observing that nothing broke."""
    result = jobs.research_jobs([], client=object(), settings=_settings())
    assert result.rows == ()
    assert result.skipped == "nothing to research"
