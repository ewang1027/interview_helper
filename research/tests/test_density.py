"""Evidence-density scoring.

The property that matters most is the aggregator guard: many pages on one site must
not outweigh two genuinely independent sources. That is the whole reason density is
computed per registrable domain rather than per URL.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from research.density import (
    HALF_LIFE_YEARS,
    TIER_WEIGHT,
    UNKNOWN_PUBLISHED_WEIGHT,
    density,
    rank,
    recency_weight,
    source_index,
)

TODAY = date(2026, 8, 16)


def test_recency_halves_over_the_half_life() -> None:
    fresh = recency_weight("2026-08-16", TODAY)
    aged = recency_weight("2023-08-16", TODAY)
    assert fresh == 1.0
    assert abs(aged - 0.5) < 0.01
    assert abs(recency_weight("2020-08-16", TODAY) - 0.25) < 0.01


def test_unknown_publication_date_uses_the_stated_default() -> None:
    assert recency_weight(None, TODAY) == UNKNOWN_PUBLISHED_WEIGHT
    # An undated page must not outrank a dated recent one.
    assert recency_weight(None, TODAY) < recency_weight("2026-01-01", TODAY)


def test_partial_dates_parse() -> None:
    assert recency_weight("2025", TODAY) > 0
    assert recency_weight("2025-06", TODAY) > recency_weight("2024-06", TODAY)


def test_future_dates_do_not_exceed_one() -> None:
    assert recency_weight("2027-01-01", TODAY) == 1.0


def _index(*entries: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return source_index([{"sources_seen": list(entries)}])


def test_five_pages_on_one_site_score_as_one_source() -> None:
    index = _index(
        *[
            {"url": f"https://aggregator.com/q{i}", "tier": "firsthand", "published": "2026-08-16"}
            for i in range(5)
        ]
    )
    item = {"sources": [{"url": f"https://aggregator.com/q{i}"} for i in range(5)]}
    assert density(item, index, TODAY) == 1.0


def test_two_independent_sites_outscore_one() -> None:
    index = _index(
        {"url": "https://one.com/a", "tier": "firsthand", "published": "2026-08-16"},
        {"url": "https://two.org/b", "tier": "firsthand", "published": "2026-08-16"},
    )
    two_sites = {"sources": [{"url": "https://one.com/a"}, {"url": "https://two.org/b"}]}
    one_site = {"sources": [{"url": "https://one.com/a"}]}
    assert density(two_sites, index, TODAY) > density(one_site, index, TODAY)


def test_subdomains_of_one_site_are_still_one_source() -> None:
    index = _index(
        {"url": "https://blog.one.com/a", "tier": "firsthand", "published": "2026-08-16"},
        {"url": "https://www.one.com/b", "tier": "firsthand", "published": "2026-08-16"},
    )
    item = {"sources": [{"url": "https://blog.one.com/a"}, {"url": "https://www.one.com/b"}]}
    assert density(item, index, TODAY) == 1.0


def test_tier_orders_firsthand_above_listicle() -> None:
    index = _index(
        {"url": "https://one.com/a", "tier": "firsthand", "published": "2026-08-16"},
        {"url": "https://two.org/b", "tier": "listicle", "published": "2026-08-16"},
    )
    first = density({"sources": [{"url": "https://one.com/a"}]}, index, TODAY)
    listicle = density({"sources": [{"url": "https://two.org/b"}]}, index, TODAY)
    assert first == TIER_WEIGHT["firsthand"]
    assert listicle == TIER_WEIGHT["listicle"]
    assert first > listicle


def test_a_url_no_run_recorded_is_scored_as_the_weakest_tier() -> None:
    # Unknown provenance must never flatter an archetype; runlog reports it separately.
    item = {"sources": [{"url": "https://unknown.com/x"}]}
    scored = density(item, {}, TODAY)
    assert scored == TIER_WEIGHT["listicle"] * UNKNOWN_PUBLISHED_WEIGHT


def test_rank_returns_archetypes_densest_first_and_skips_instances() -> None:
    index = _index(
        {"url": "https://one.com/a", "tier": "firsthand", "published": "2026-08-16"},
        {"url": "https://two.org/b", "tier": "firsthand", "published": "2026-08-16"},
    )
    strong = {
        "id": "a.code.0002",
        "kind": "archetype",
        "sources": [{"url": "https://one.com/a"}, {"url": "https://two.org/b"}],
    }
    weak = {"id": "a.code.0001", "kind": "archetype", "sources": [{"url": "https://one.com/a"}]}
    instance = {"id": "i.code.0001", "kind": "instance", "sources": [{"url": "https://one.com/a"}]}

    ranked = rank([weak, instance, strong], index, TODAY)
    assert [item["id"] for item, _ in ranked] == ["a.code.0002", "a.code.0001"]


def test_half_life_is_the_documented_three_years() -> None:
    assert HALF_LIFE_YEARS == 3.0
