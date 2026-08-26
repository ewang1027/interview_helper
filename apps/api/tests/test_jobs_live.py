"""The job tracker against real models — the gap docs/JOBS.md has carried since it landed.

Marked `llm`: it spends money and needs credentials, so it is deselected by default and
run deliberately —

    make test-llm        # needs credentials, a live Postgres, and model access

Every other test of this feature scripts both calls, which proves the plumbing and proves
nothing about the **prompts** — and the prompts are the part that has to survive input a
person pasted without thinking about a parser. So the paste below is deliberately nasty:
inconsistent separators, a bare company name with no title, a stage buried in prose, a
date in one row and not the others, and a trailing line that is not an application at all.

The research half is skipped rather than failed when the provider cannot do it. Web search
is a first-party Claude API tool and **Bedrock does not have it**, so a Bedrock deployment
running this suite should report "not applicable", not "broken".

Every company in the paste is invented. This repo is public, and a fixture naming real
applications would be the one way this feature leaks something that matters. The research
test is the exception and has to be: web search needs a posting that exists, so it uses two
well-known employers as *search targets*. Neither is an application anybody made.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlmodel import Session, col, delete, select

from api import jobs
from api.db import get_engine
from api.errors import ProblemError
from api.models import JobApplication, JobApplicationEvent, LlmCall
from api.settings import get_settings

pytestmark = pytest.mark.llm


# Messy on purpose. Five applications and one line that is not one.
PASTE = """\
jobs i've applied to so far --

1. Aurora Labs - backend engineer (applied 2026-07-04)
2. Northwind Systems, Quantitative Trader — did their online assessment last week
3. Helio Robotics / Machine Learning Engineer / rejected after the first round
4. Vantage Peak Capital  ...  quant research, onsite next thursday!!
5. Calder & Finch

follow up with the recruiter about #2
"""


@pytest.fixture
def cleanup() -> Iterator[None]:
    """Remove exactly what this test wrote — by difference against a snapshot, not by user.

    Written as "every application belonging to the local user" first, which is the same
    over-deletion that destroyed a real job list on 2026-08-26. Fixed in the db tests and
    missed here, then caught by the canary in `conftest` on its first run against this
    file — so `make test-llm` would have deleted the same list all over again.
    """
    with Session(get_engine()) as db:
        applications_before = set(db.exec(select(JobApplication.id)).all())
        calls_before = set(db.exec(select(LlmCall.id)).all())
    yield
    with Session(get_engine()) as db:
        mine = list(set(db.exec(select(JobApplication.id)).all()) - applications_before)
        if mine:
            db.exec(
                delete(JobApplicationEvent).where(col(JobApplicationEvent.application_id).in_(mine))
            )
            db.exec(delete(JobApplication).where(col(JobApplication.id).in_(mine)))
        new = list(set(db.exec(select(LlmCall.id)).all()) - calls_before)
        if new:
            db.exec(delete(LlmCall).where(col(LlmCall.id).in_(new)))
        db.commit()


def test_a_real_model_parses_a_list_a_person_would_actually_paste(cleanup) -> None:
    """The parse, against the real provider and the real prompt.

    The assertions are about what the prompt is *for*, not about exact strings — a model
    is free to call row 5's role "Software Engineer" or "Engineer", and pinning that would
    be testing the model rather than the prompt. What must hold is structural: five rows
    and not six, the taxonomy respected, and the stages the paste actually stated.
    """
    settings = get_settings()
    try:
        parsed = jobs.parse_jobs(PASTE, settings=settings)
    except ProblemError as exc:
        pytest.skip(f"provider unavailable: {exc.detail}")

    rows = parsed.rows
    companies = {row.company.lower() for row in rows}

    # Five applications. The trailing "follow up with the recruiter" line is not one, and
    # a parser that turns it into a row is the failure this paste exists to provoke.
    assert len(rows) == 5, f"expected 5 rows, got {len(rows)}: {[r.company for r in rows]}"
    for expected in ["aurora", "northwind", "helio", "vantage", "calder"]:
        assert any(expected in company for company in companies), f"lost {expected}: {companies}"

    by_company = {row.company.lower(): row for row in rows}

    def find(fragment: str) -> jobs.ParsedJob:
        return next(row for company, row in by_company.items() if fragment in company)

    # Every tag is in the taxonomy — guaranteed by the enum in the schema, asserted because
    # that guarantee is the reason the enum is there.
    for row in rows:
        assert row.subcategory in jobs.CATEGORY_FOR_SUBCATEGORY
        assert row.category in jobs.CATALOG
        assert row.stage in jobs.STAGES

    # The categories the tracker exists to separate. A quant trading role at a fund and a
    # backend role at a lab must not land in the same bucket.
    assert find("aurora").category == "swe"
    assert find("northwind").category == "quant"
    assert find("helio").category == "ai"
    assert find("vantage").category == "quant"

    # Stages stated in prose, not in a field.
    assert find("northwind").stage == "oa"
    assert find("helio").stage in {"rejected", "round_1"}
    assert find("vantage").stage in {"final", "round_1", "round_2", "phone_screen"}
    # Nothing was said about Calder & Finch beyond the name, so it is `applied` — and the
    # model should be unsure of a tag it inferred from a company name alone.
    assert find("calder").stage == "applied"

    # The one date the paste gives, and only that one.
    assert find("aurora").applied_on is not None
    assert find("aurora").applied_on.isoformat() == "2026-07-04"
    assert find("northwind").applied_on is None

    print(
        f"\nparse: {len(rows)} rows · {parsed.model} · ${parsed.cost_usd:.4f}\n"
        + "\n".join(
            f"  {row.company:24} {row.role:34} {row.category:6}/{row.subcategory:18} "
            f"{row.stage:12} conf={row.confidence:.2f}"
            for row in rows
        )
    )


def test_the_research_pass_actually_searches_the_web(cleanup) -> None:
    """The Opus 5 half, including a real billed search.

    What this proves that no scripted test can: that the tool is declared in a shape the
    provider accepts, that the model answers through `record_applications` rather than in
    prose, and that the searches it makes come back on the response where the ledger can
    price them.

    The rows are deliberately thin — a real company and a vague title — because filling
    those in is the entire job.
    """
    settings = get_settings()
    blocked = jobs.research_available(settings)
    if blocked:
        pytest.skip(f"research pass not available here: {blocked}")

    given = [
        jobs.ParsedJob(company="Anthropic", role="engineer", stage="oa", confidence=0.3),
        jobs.ParsedJob(company="Jane Street", role="trader", stage="applied", confidence=0.3),
    ]
    result = jobs.research_jobs(given, settings=settings)

    if result.skipped:
        pytest.fail(f"the research pass did not complete: {result.skipped}")

    # The contract that matters most: same rows, same order, same length.
    assert len(result.rows) == len(given)
    assert [row.company for row in result.rows] == [row.company for row in given]

    # The stage came from the person, not the web, and must survive the round trip.
    assert [row.stage for row in result.rows] == ["oa", "applied"]

    # It actually searched, and the searches are on the response — which is the number the
    # ledger prices at $10/1,000 and the only cost that appears in no token counter.
    assert result.web_searches > 0, "the research pass returned without searching"

    with Session(get_engine()) as db:
        row = db.exec(
            select(LlmCall)
            .where(LlmCall.job == "job_research")
            .order_by(col(LlmCall.created_at).desc())
        ).first()
    assert row is not None
    assert row.web_search_requests == result.web_searches
    assert row.cost_usd >= result.web_searches * 0.01

    print(
        f"\nresearch: {result.model} · {result.web_searches} searches · ${result.cost_usd:.4f}\n"
        + "\n".join(
            f"  {row.company:14} {row.role:44} {row.subcategory:18} conf={row.confidence:.2f}\n"
            f"      {(row.notes or '')[:100]}"
            for row in result.rows
        )
    )


def test_the_taxonomy_prompt_is_worth_a_cache_breakpoint(cleanup) -> None:
    """Is the parse's system prompt actually cacheable, or is the breakpoint decoration?

    `api.llm.cached_system` marks every system prompt with `cache_control`, but the API's
    minimum cacheable prefix is about 1024 tokens — below that the marker is accepted and
    silently does nothing. The taxonomy block is 31 sub-categories and a page of
    instructions, which is close enough to that floor to be worth measuring rather than
    assuming, since the only symptom of a wrong answer here is the bill.

    This asserts nothing about which side of the line it falls on; it reports it, so
    docs/COST.md can say something true.
    """
    settings = get_settings()
    if settings.model_provider != "anthropic":
        pytest.skip("token counting is a first-party API endpoint")

    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)

    def count(system: str | None, message: str) -> int:
        return client.messages.count_tokens(
            model=settings.model_job_parser,
            **({"system": system} if system else {}),
            messages=[{"role": "user", "content": message}],
        ).input_tokens

    # The *system block alone* is what carries the breakpoint, so it is the number that has
    # to clear the floor — measured by difference, since `count_tokens` always prices a
    # message too and the floor does not care about the message.
    baseline = count(None, ".")
    with_system = count(jobs.taxonomy_prompt(), ".")
    system_tokens = with_system - baseline
    whole = count(jobs.taxonomy_prompt(), PASTE)

    print(
        f"\nparse prompt: system block {system_tokens} tokens "
        f"(cache floor ~1024) · whole request {whole} tokens"
    )
    # Measured 882 on 2026-08-26: **below the floor**, so the `cache_control` breakpoint
    # `api.llm.cached_system` puts on every system prompt is accepted and does nothing
    # here. Not worth padding the prompt to fix — at 882 tokens a 90% saving is a fraction
    # of a cent — but worth knowing, because "we cache the taxonomy" was the assumption.
    #
    # A tripwire in both directions: if the catalogue grows past the floor this starts
    # failing, and caching will have switched itself on without anyone deciding to.
    assert system_tokens < 1024, (
        f"the taxonomy prompt is now {system_tokens} tokens and clears the ~1024 cache "
        "floor — caching is live for this call; update docs/COST.md and this assertion"
    )
