"""Evidence-density ranking — the one place archetypes get ordered.

`docs/RESEARCH.md` §4: rank archetypes by how many *independent* sources attest them,
weighted by recency and source quality. Never by asking a model to score novelty or
importance — LLM-judged novelty correlates negatively with real impact, so ranking on
it actively selects for worse material. Density is a count, not an opinion.

    density = sum over distinct registrable domains of (recency_weight * tier_weight)

Two deliberate details:

- **Per registrable domain, only the best source counts.** Five pages on one aggregator
  is one source, so the domain contributes its strongest entry and nothing more.
- **Quality tier and publication date live in the run record, not on the item.** The
  item schema carries no quality judgement on purpose: a source's tier is an assessment
  made during a sweep, and it belongs with the sweep that made it.

Run with `make research-rank`.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from typing import Any

from corpus.loader import CorpusPaths, load_raw_items
from corpus.validate import registrable_domain
from research.runlog import ResearchPaths, load_runs

# A first-hand loop writeup outranks a listicle. Coarse on purpose — a finer scale
# would imply a precision this judgement does not have.
TIER_WEIGHT: dict[str, float] = {"firsthand": 1.0, "curated": 0.7, "listicle": 0.4}

# Interview patterns shift; evidence halves in weight every three years.
HALF_LIFE_YEARS = 3.0

# A page with no stated publication date. Chosen as a stated default rather than
# guessing a date — an unknown-age source should not outrank a dated recent one.
UNKNOWN_PUBLISHED_WEIGHT = 0.6


def _parse_published(published: str | None) -> date | None:
    """Accept YYYY, YYYY-MM, or YYYY-MM-DD. Partial dates resolve to the 1st."""
    if not published:
        return None
    parts = published.split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else 1
    day = int(parts[2]) if len(parts) > 2 else 1
    return date(year, month, day)


def recency_weight(published: str | None, today: date) -> float:
    parsed = _parse_published(published)
    if parsed is None:
        return UNKNOWN_PUBLISHED_WEIGHT
    age_years = (today - parsed).days / 365.25
    if age_years <= 0:
        return 1.0
    return float(0.5 ** (age_years / HALF_LIFE_YEARS))


def source_index(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """URL -> the run-record entry for it. Later runs win, so a re-tiered source updates."""
    index: dict[str, dict[str, Any]] = {}
    for run in runs:
        for src in run.get("sources_seen", []):
            index[src["url"]] = src
    return index


def density(item: dict[str, Any], index: dict[str, dict[str, Any]], today: date) -> float:
    best_per_domain: dict[str, float] = defaultdict(float)
    for src in item.get("sources", []):
        url = src.get("url", "")
        entry = index.get(url, {})
        tier = TIER_WEIGHT.get(str(entry.get("tier", "listicle")), TIER_WEIGHT["listicle"])
        weight = tier * recency_weight(entry.get("published"), today)
        host = registrable_domain(url)
        best_per_domain[host] = max(best_per_domain[host], weight)
    return sum(best_per_domain.values())


def rank(
    items: list[dict[str, Any]], index: dict[str, dict[str, Any]], today: date
) -> list[tuple[dict[str, Any], float]]:
    """Archetypes only, densest first. Instances inherit their archetype's ranking."""
    archetypes = [i for i in items if i.get("kind") == "archetype"]
    scored = [(a, density(a, index, today)) for a in archetypes]
    return sorted(scored, key=lambda pair: (-pair[1], str(pair[0].get("id"))))


def main(argv: list[str] | None = None) -> int:
    del argv
    items = load_raw_items(CorpusPaths.default())
    index = source_index(load_runs(ResearchPaths.default()))
    today = date.today()

    ranked = rank(items, index, today)
    if not ranked:
        print("no archetypes yet — run a sweep first")
        return 0

    instances_per: dict[str, int] = defaultdict(int)
    for item in items:
        if item.get("kind") == "instance":
            instances_per[str(item.get("archetype_id"))] += 1

    by_domain: dict[str, list[tuple[dict[str, Any], float]]] = defaultdict(list)
    for archetype, score in ranked:
        by_domain[str(archetype.get("domain"))].append((archetype, score))

    for domain in sorted(by_domain):
        print(f"\n== {domain} ({len(by_domain[domain])} archetypes)")
        print(f"{'density':>8}  {'srcs':>4}  {'inst':>4}  id             title")
        for archetype, score in by_domain[domain]:
            aid = str(archetype.get("id"))
            hosts = {registrable_domain(s["url"]) for s in archetype.get("sources", [])}
            print(
                f"{score:8.2f}  {len(hosts):4d}  {instances_per[aid]:4d}  "
                f"{aid:<14} {archetype.get('title')}"
            )
    print(f"\n{len(ranked)} archetypes ranked by evidence density (half-life {HALF_LIFE_YEARS}y)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
