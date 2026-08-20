"""Choosing what a session serves.

**This is a placeholder, and says so in every plan it produces.** docs/ADAPTIVE.md's
planner ranks concepts by weakness, respects the prerequisite DAG, and targets items whose
expected score lands in the informative band — all of which needs `mastery`, which needs
evidence, which needs sessions to exist first. So this wave gets the simplest selection
that is honest about being simple: filter by mode, order by distance from a difficulty
target, fill the time budget.

Every plan carries `"adaptive": false` and the strategy name, so nothing downstream — and
nobody reading a session — can mistake this for the engine that replaces it in Phase 4.

The corpus is the source of truth for *what an item is*; the `items` table is a projection
of it (docs/ARCHITECTURE.md). Planning therefore reads the corpus, and the session service
separately checks that the ids it chose are present in the database, so an unseeded
database fails with a sentence rather than a foreign-key error.
"""

from __future__ import annotations

from typing import Any

from corpus.loader import load_items
from corpus.models import Item

STRATEGY = "corpus-order-placeholder@1"

# The middle of the corpus's declared Elo range (600..2800). docs/ADAPTIVE.md will replace
# this with the candidate's own ability per concept; until evidence exists there is no
# such number, and pretending otherwise is the "opaque adaptation" the API doc warns about.
NEUTRAL_ELO = 1400.0

# How far one step of `difficulty_bias` (-1..+1, advisory) moves the target.
BIAS_STEP_ELO = 300.0

# Used when an item declares no `expected_minutes`, so budget arithmetic still terminates.
ASSUMED_MINUTES = 20


def eligible_items(mode: str, focus_concepts: tuple[str, ...] = ()) -> list[Item]:
    """Active instances for `mode`. Archetypes are patterns, not gradeable problems."""
    items = [
        item
        for item in load_items()
        if item.kind == "instance" and item.is_active and item.modality == mode
    ]
    if focus_concepts:
        wanted = set(focus_concepts)
        items = [item for item in items if wanted.intersection(item.concepts)]
    return items


def build_plan(
    mode: str,
    budget_minutes: int,
    *,
    focus_concepts: tuple[str, ...] = (),
    difficulty_bias: float = 0.0,
) -> dict[str, Any]:
    """Pick items for one session and say why they were picked."""
    target_elo = NEUTRAL_ELO + difficulty_bias * BIAS_STEP_ELO
    candidates = eligible_items(mode, focus_concepts)
    # Distance to the target, then id: fully deterministic, so the same request twice
    # produces the same session. A planner that shuffled would make a bug unreproducible.
    candidates.sort(key=lambda item: (abs(item.difficulty.elo - target_elo), item.id))

    chosen: list[Item] = []
    spent = 0
    for item in candidates:
        minutes = item.expected_minutes or ASSUMED_MINUTES
        if chosen and spent + minutes > budget_minutes:
            continue
        chosen.append(item)
        spent += minutes
        if spent >= budget_minutes:
            break

    return {
        "strategy": STRATEGY,
        "adaptive": False,
        "why": (
            "Placeholder selection: eligible items ordered by distance from a fixed "
            "difficulty target, filled to the time budget. No mastery data exists yet, so "
            "nothing here is adapted to you — docs/ADAPTIVE.md, Phase 4."
        ),
        "mode": mode,
        "budget_minutes": budget_minutes,
        "target_elo": target_elo,
        "focus_concepts": list(focus_concepts),
        "estimated_minutes": spent,
        "items": [
            {
                "item_id": item.id,
                "title": item.title,
                "primary_concept": item.primary_concept,
                "expected_minutes": item.expected_minutes,
                "elo": item.difficulty.elo,
            }
            for item in chosen
        ],
    }


def plan_item_ids(plan: dict[str, Any] | None) -> list[str]:
    return [entry["item_id"] for entry in (plan or {}).get("items", [])]
