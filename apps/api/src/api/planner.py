"""Choosing what a session serves.

docs/ADAPTIVE.md's planner: rank concepts by weakness priority, respect the prerequisite
DAG, and select items whose *expected* score lands in the band where an outcome is
actually informative. Below about 0.6 you fail for uninformative reasons; above about
0.75 the item confirms what is already known.

Every plan carries its own reasoning — which concept each item was chosen for, what the
engine expected you to score, and the priority terms behind that concept's rank. Opaque
adaptation is untrustworthy adaptation, and a weight that turns out to be wrong is only
findable if the plan says which term dominated.

**Two honest limits at this corpus size.** With 24 items, three of them coding, the
prerequisite gate usually has nowhere to send you: `monotonic-stack`'s prerequisite is
`stack-simulation`, and no item measures it. So the substitution is attempted, and when
the corpus cannot honour it the plan says the concept was kept and why. And a plan can
only ever contain items that exist — a session may repeat what you saw last time simply
because there is nothing else, which the anti-repetition term cannot fix by itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, col, select

from api.mastery import DEFAULT_ABILITY, expected_score
from api.models import ConceptEdge, Item, Mastery
from api.priority import ConceptPriority, rank_concepts
from corpus.loader import load_items
from corpus.models import Item as CorpusItem

STRATEGY = "weakness-priority@1"

# Which concept taxonomy a session mode draws from. The two vocabularies differ by one
# name — the modality is `design`, the domain is `system_design` — and conflating them
# silently produces an empty plan.
DOMAIN_FOR_MODE = {
    "coding": "coding",
    "quant": "quant",
    "design": "system_design",
    "behavioral": "behavioral",
}

# The informative band: an item you are expected to score inside this range teaches
# something whichever way it goes.
BAND_LOW = 0.60
BAND_HIGH = 0.75

# `difficulty_bias` is advisory (docs/API.md). It shifts the band rather than overriding
# it: +1 aims at items you are expected to find harder, not at the hardest item on file.
BIAS_SHIFT = 0.10

# Used when an item declares no `expected_minutes`, so budget arithmetic terminates.
ASSUMED_MINUTES = 20

# At most one item per session is review of material you are *good* at, so fluency on
# solved ground does not rot while the planner drills weaknesses. It is reserved *before*
# the weakness pass fills the budget, and the weakness pass then skips it.
#
# There is no fractional share any more, and that is a correction rather than a
# simplification. A "quarter of the budget" is 11 minutes of a 45-minute session, and the
# shortest item in the corpus is 20 — so the cap was smaller than anything it could buy,
# and the weakness pass had already eaten the rest of the budget by the time review was
# considered. The minority is enforced by "at most one, chosen after the weaknesses are
# ranked", which is a rule that can actually fire.

# How good "good at it" is, in Elo — the same units as the rating itself.
#
# This was a *normalised* 0.55, which is an Elo of 1810: 260 points above where a concept
# starts. Simulated against this corpus with the real K decay, that floor is first crossed
# on the **55th** consecutive success, because beating an item also drags the item's rating
# down and shrinks every subsequent gain. The review slot could not fire, and nothing said
# so — a documented feature, dormant, with a passing test suite.
REVIEW_ABILITY_FLOOR_ELO = DEFAULT_ABILITY + 60.0


def eligible_items(mode: str, focus_concepts: tuple[str, ...] = ()) -> list[CorpusItem]:
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


def _prerequisite_substitution(
    db: Session,
    entry: ConceptPriority,
    by_id: dict[str, ConceptPriority],
    serveable: set[str],
) -> tuple[str, str | None]:
    """Serve a weak prerequisite instead of the concept it gates.

    docs/ADAPTIVE.md: "it will not serve `dp-knapsack` while `dp-1d` is weak; it serves
    `dp-1d`. This is the one place the DAG is a hard gate rather than a hint." It is a
    gate only as far as the corpus allows: substituting toward a concept with no items
    would produce an empty session, so an unserveable prerequisite is reported and the
    original concept is kept.
    """
    prereqs = [
        edge.prereq_id
        for edge in db.exec(select(ConceptEdge).where(ConceptEdge.concept_id == entry.concept_id))
    ]
    weaker = [
        by_id[prereq]
        for prereq in prereqs
        if prereq in by_id and by_id[prereq].ability < entry.ability
    ]
    if not weaker:
        return entry.concept_id, None

    weakest = min(weaker, key=lambda candidate: candidate.ability)
    if weakest.concept_id not in serveable:
        return entry.concept_id, (
            f"{weakest.concept_id} gates it and is weaker, but no item measures it"
        )
    return weakest.concept_id, f"substituted for {entry.concept_id}, whose prerequisite it is"


def _band_distance(expected: float, low: float, high: float) -> float:
    if expected < low:
        return low - expected
    if expected > high:
        return expected - high
    return 0.0


def build_plan(
    db: Session,
    user_id: str,
    mode: str,
    budget_minutes: int,
    *,
    focus_concepts: tuple[str, ...] = (),
    difficulty_bias: float = 0.0,
) -> dict[str, Any]:
    """Pick items for one session and record why each one was picked."""
    domain = DOMAIN_FOR_MODE[mode]
    candidates = eligible_items(mode, focus_concepts)
    by_primary: dict[str, list[CorpusItem]] = {}
    for item in candidates:
        by_primary.setdefault(item.primary_concept, []).append(item)

    live_elo = {
        row.id: row.elo
        for row in db.exec(
            select(Item).where(col(Item.id).in_([item.id for item in candidates]))
        ).all()
    }
    ability = {
        row.concept_id: row.ability
        for row in db.exec(select(Mastery).where(Mastery.user_id == user_id)).all()
    }
    ranked = rank_concepts(db, user_id, domain=domain)
    if focus_concepts:
        wanted = set(focus_concepts)
        ranked = [entry for entry in ranked if entry.concept_id in wanted] or ranked
    by_id = {entry.concept_id: entry for entry in ranked}

    low, high = BAND_LOW - difficulty_bias * BIAS_SHIFT, BAND_HIGH - difficulty_bias * BIAS_SHIFT
    total_observations = sum(entry.observations for entry in ranked)

    # Pass one: the best item for each concept, with how far it sits from the informative
    # band. Pass two fills the budget in priority order, breaking ties by that distance.
    #
    # The tie-break earns its keep exactly at cold start, where every concept has the same
    # priority because nothing has been measured — without it, the first session is chosen
    # by whichever concept id sorts first alphabetically. Measured: it served an item the
    # candidate was expected to score 0.43 on, while an item sitting squarely in the band
    # went unserved.
    shortlist: list[tuple[float, float, str, CorpusItem, dict[str, Any]]] = []
    seen_concepts: set[str] = set()
    for entry in ranked:
        concept_id, note = _prerequisite_substitution(db, entry, by_id, set(by_primary))
        if concept_id in seen_concepts:
            continue
        pool = by_primary.get(concept_id, [])
        if not pool:
            continue
        seen_concepts.add(concept_id)

        target = by_id.get(concept_id, entry)
        expectations = {
            item.id: expected_score(
                ability.get(concept_id, target.ability), live_elo.get(item.id, item.difficulty.elo)
            )
            for item in pool
        }
        item = min(pool, key=lambda i: (_band_distance(expectations[i.id], low, high), i.id))
        distance = _band_distance(expectations[item.id], low, high)
        shortlist.append(
            (
                target.priority,
                distance,
                concept_id,
                item,
                {
                    "targets": concept_id,
                    "priority": target.priority,
                    "terms": target.terms,
                    "expected_score": expectations[item.id],
                    "in_band": distance == 0.0,
                    "calibrating": target.calibrating,
                    "prerequisite_note": note,
                },
            )
        )

    # Rounded, because two priorities that differ in the sixteenth decimal are a tie in
    # every sense that matters, and float noise would silently disable the tie-break.
    shortlist.sort(key=lambda row: (-round(row[0], 6), row[1], row[3].id))

    # Reserved first, and excluded from the pass below. A greedy fill always leaves less
    # than one item's worth of budget behind, so a review slot considered afterwards could
    # never be filled — the feature was unreachable rather than merely rare.
    review = _review_item(db, user_id, by_primary, ability, live_elo)
    reserved = review["expected_minutes"] or ASSUMED_MINUTES if review else 0
    weakness_budget = max(0, budget_minutes - reserved)

    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    spent = 0
    for _priority, _distance, concept_id, item, reason in shortlist:
        if review is not None and item.id == review["item_id"]:
            continue
        if spent >= weakness_budget and chosen:
            break
        minutes = item.expected_minutes or ASSUMED_MINUTES
        if chosen and spent + minutes > weakness_budget:
            continue
        used.add(item.id)
        spent += minutes
        chosen.append(
            {
                "item_id": item.id,
                "title": item.title,
                "primary_concept": concept_id,
                "expected_minutes": item.expected_minutes,
                "elo": live_elo.get(item.id, item.difficulty.elo),
                "reason": reason,
            }
        )

    if review is not None and spent + reserved <= budget_minutes:
        chosen.append(review)
        spent += reserved

    calibration = total_observations == 0
    return {
        "strategy": STRATEGY,
        "adaptive": True,
        "calibration": calibration,
        "why": (
            "No evidence yet, so this is a calibration spread: concepts ranked by what they "
            "unlock, at mid-band difficulty, to find out where you stand."
            if calibration
            else "Concepts ranked by weakness priority; for each, the item whose expected "
            "score lands closest to the informative band."
        ),
        "mode": mode,
        "budget_minutes": budget_minutes,
        "band": [low, high],
        "focus_concepts": list(focus_concepts),
        "estimated_minutes": spent,
        "items": chosen,
        # The concepts it weighed, not just the ones it served — the ranking is the part
        # worth arguing with, and it is invisible from the item list alone.
        "considered": [entry.as_dict() for entry in ranked[:5]],
    }


def _review_item(
    db: Session,
    user_id: str,
    by_primary: dict[str, list[CorpusItem]],
    ability: dict[str, float],
    live_elo: dict[str, float],
) -> dict[str, Any] | None:
    """The one due item you are *good* at that a session should re-serve, if any.

    docs/ADAPTIVE.md asks the planner to keep a minority of due-for-review items among the
    weaknesses, so fluency on solved material does not rot. Deliberately at most one: this
    is a session about what you are bad at, and review is the seasoning. Whether it fits is
    the caller's decision — this only says which item it would be.
    """
    now = datetime.now(UTC)
    # Ordered in SQL, not just sorted after: `sorted` is stable over whatever order
    # Postgres returned, so two concepts due at the same instant would pick differently
    # between runs. Every other tie in this module is broken explicitly.
    due = [
        row
        for row in db.exec(
            select(Mastery)
            .where(Mastery.user_id == user_id)
            .order_by(col(Mastery.due_at), col(Mastery.concept_id))
        ).all()
        if row.due_at is not None
        and row.due_at.astimezone(UTC) <= now
        and row.ability >= REVIEW_ABILITY_FLOOR_ELO
    ]
    for row in due:
        for item in by_primary.get(row.concept_id, []):
            return {
                "item_id": item.id,
                "title": item.title,
                "primary_concept": row.concept_id,
                "expected_minutes": item.expected_minutes,
                "elo": live_elo.get(item.id, item.difficulty.elo),
                "reason": {
                    "targets": row.concept_id,
                    "priority": None,
                    "terms": {},
                    "expected_score": expected_score(
                        ability.get(row.concept_id, row.ability),
                        live_elo.get(item.id, item.difficulty.elo),
                    ),
                    "in_band": None,
                    "calibrating": False,
                    "prerequisite_note": "due for review, and you are good at it",
                },
            }
    return None


def plan_item_ids(plan: dict[str, Any] | None) -> list[str]:
    return [entry["item_id"] for entry in (plan or {}).get("items", [])]
