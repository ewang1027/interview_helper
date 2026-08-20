"""Ratings and scheduling — the projection `concept_evidence` is replayed into.

docs/ADAPTIVE.md's two numbers, and the rule that makes them trustworthy: **nothing is
written to `mastery` except by replaying evidence.** Every function here takes an evidence
row and returns the state it implies, so the table can be rebuilt from scratch at any
time. That is what lets a grader bug be fixed by correcting evidence and re-running,
rather than by hand-patching a number nobody can trace.

- **`ability`** — Elo per (user, concept), against the item's own live rating. Answers
  *how hard should the next item be*.
- **`stability` / `due_at`** — FSRS, from the `fsrs` package rather than hand-rolled
  arithmetic. Answers *when should I see this again*.

Two things about that scheduler are load-bearing:

**Fuzzing is off.** `Scheduler` enables it by default, which jitters each interval so a
schedule is pleasant to use rather than reproducible. Measured here: six identical reviews
of an identical card produced **six different due dates**. Under a design whose central
claim is "the projection can be rebuilt from the evidence", that is not a nicety — it is
the difference between a replay test that means something and one that cannot pass.

**Learning steps are empty.** FSRS ships flashcard defaults that re-show a card after one
minute and ten minutes. A concept in a mock interview is not re-drilled sixty seconds
later; an interval that short would produce a due date that is always in the past and a
weakness signal that is always screaming. With no learning steps a first review goes
straight to a stability-based interval.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from fsrs import Card, Rating, Scheduler
from fsrs.card import CardDict
from sqlmodel import Session, col, select

from api.models import ConceptEvidence, Item, Mastery

# --- Elo ------------------------------------------------------------------------------

# The rating a concept starts at, matching `mastery.ability`'s column default and sitting
# mid-way through the corpus's declared 600..2800 band.
DEFAULT_ABILITY = 1200.0

# K decays with the number of observations for that concept: early evidence should move
# the estimate quickly, later evidence refine it. Chosen, not calibrated — five sessions of
# real data is what would justify different numbers.
K_MAX = 48.0
K_MIN = 10.0
K_HALFLIFE = 8.0

# "K_item is much smaller than K. Item ratings should move slowly; with one user, they are
# mostly a prior." — docs/ADAPTIVE.md
K_ITEM = 4.0

# Below this many observations a concept is still calibrating: the estimate is not yet
# worth much, which the planner and any UI should say out loud rather than imply.
CALIBRATION_OBSERVATIONS = 5

# The corpus's own Elo range, used to normalise ability into [0, 1] for the weakness
# priority. Not a clamp on the rating itself — a rating may drift outside it.
ELO_FLOOR = 600.0
ELO_CEILING = 2800.0


def k_factor(observations: int) -> float:
    """How far one result is allowed to move an estimate."""
    return max(K_MIN, K_MAX / (1.0 + observations / K_HALFLIFE))


def expected_score(ability: float, item_elo: float) -> float:
    """The logistic Elo expectation: 0.5 at equal ratings, ~0.91 at +400."""
    return float(1.0 / (1.0 + 10.0 ** ((item_elo - ability) / 400.0)))


def is_calibrating(observations: int) -> bool:
    return observations < CALIBRATION_OBSERVATIONS


def normalized_ability(ability: float) -> float:
    span = ELO_CEILING - ELO_FLOOR
    return min(1.0, max(0.0, (ability - ELO_FLOOR) / span))


# --- Scheduling -----------------------------------------------------------------------

SCHEDULER = Scheduler(enable_fuzzing=False, learning_steps=(), relearning_steps=())

# A graded score is continuous; FSRS takes one of four grades. The thresholds are a
# judgement call, stated here rather than buried: anything under half is a lapse, and only
# a near-perfect run earns the interval `Easy` buys.
RATING_THRESHOLDS = ((0.5, Rating.Again), (0.75, Rating.Hard), (0.95, Rating.Good))


def rating_for(score: float) -> Rating:
    for threshold, rating in RATING_THRESHOLDS:
        if score < threshold:
            return rating
    return Rating.Easy


# --- Applying evidence ----------------------------------------------------------------


def as_utc(moment: datetime) -> datetime:
    """Normalise an instant to `datetime.timezone.utc` before handing it to FSRS.

    Not paranoia, and not a no-op. A timestamp written as `timezone.utc` comes back from
    Postgres as `ZoneInfo("Etc/UTC")` — same instant, same offset, **different object** —
    and FSRS compares `tzinfo` against `timezone.utc` by equality, so it rejects the
    round-tripped value with "datetime must be timezone-aware and set to UTC".

    Which means the incremental path worked (in-memory rows never left Python) while the
    replay path raised. The gate test for replay is what surfaced it, on its first run.
    """
    return moment.astimezone(UTC)


def _row_for(db: Session, user_id: str, concept_id: str) -> Mastery:
    row = db.get(Mastery, (user_id, concept_id))
    if row is None:
        row = Mastery(user_id=user_id, concept_id=concept_id, ability=DEFAULT_ABILITY)
        db.add(row)
    return row


def apply_evidence(db: Session, evidence: ConceptEvidence, *, user_id: str) -> Mastery:
    """Fold one evidence row into the projection. Never writes evidence, only reads it.

    `confidence` scales both Elo updates, per docs/ADAPTIVE.md: a hidden-test pass is
    near-certain evidence about a concept, an LLM rubric's read is softer, and the rating
    should move accordingly. It does **not** scale the schedule — FSRS takes a grade, and
    inventing a fractional review would be arithmetic nobody can check.
    """
    row = _row_for(db, user_id, evidence.concept_id)

    item = db.get(Item, evidence.item_id) if evidence.item_id else None
    # A practice-log row has no item and therefore no opponent rating. Grading it against
    # the candidate's own current ability makes the expectation 0.5 — the honest reading of
    # "we do not know how hard this was" — instead of inventing a difficulty for it.
    item_elo = item.elo if item is not None else row.ability

    expected = expected_score(row.ability, item_elo)
    delta = evidence.score - expected
    k = k_factor(row.observations) * evidence.confidence

    row.ability += k * delta
    row.observations += 1

    # The item moves the other way and far less: a candidate scoring above expectation is
    # evidence the item was easier than its author guessed.
    #
    # **Only the primary concept's row moves it.** One graded submission writes one
    # evidence row per concept the item names — four, for the coding items on disk — and
    # updating the item on each of them made its rating drift four times faster than an
    # item that happens to list one concept. Measured: 9.1 points from a single session
    # against a K_ITEM of 4. An item's rating is a fact about *the attempt*, so it moves
    # once per attempt, and tying that to the primary concept's row keeps it derivable
    # from evidence alone — which is what a replay needs.
    if item is not None and evidence.concept_id == item.primary_concept_id:
        item.elo -= K_ITEM * delta * evidence.confidence
        db.add(item)

    # `CardDict` is a TypedDict and the column is plain JSONB, so the two need a cast in
    # each direction. The round trip itself is the library's own, which is the point of
    # storing its dict rather than a hand-picked subset of fields.
    card = Card.from_dict(cast(CardDict, row.fsrs_card)) if row.fsrs_card else Card()
    card, _log = SCHEDULER.review_card(
        card, rating_for(evidence.score), review_datetime=as_utc(evidence.ts)
    )
    row.fsrs_card = dict(card.to_dict())
    row.stability = card.stability
    row.due_at = card.due
    row.last_seen = evidence.ts

    db.add(row)
    return row


def recompute(db: Session, user_id: str) -> dict[str, int]:
    """Rebuild the whole projection from `concept_evidence`, in timestamp order.

    Item ratings are rebuilt too. They are as much a projection of evidence as `ability`
    is — `items.difficulty_elo` holds the author's prior, and `items.elo` is what real
    outcomes have made of it — so a rebuild that reset only half the state would produce a
    table that no replay could reproduce.

    Ordered by `(ts, id)`. `ts` is microsecond-resolution, so ties are vanishingly rare —
    and when they do happen the rows share a grading, which means they are for *different*
    concepts, whose projections are independent. Order between them cannot change the
    result. (ULIDs sort by creation time only to the millisecond, so `id` is a tie-break,
    not a guarantee.)
    """
    for row in db.exec(select(Mastery).where(Mastery.user_id == user_id)).all():
        db.delete(row)
    db.flush()

    for item in db.exec(select(Item)).all():
        item.elo = item.difficulty_elo
        db.add(item)
    db.flush()

    rows = db.exec(
        select(ConceptEvidence).order_by(col(ConceptEvidence.ts), col(ConceptEvidence.id))
    ).all()
    for evidence in rows:
        apply_evidence(db, evidence, user_id=user_id)

    db.commit()
    concepts = db.exec(select(Mastery).where(Mastery.user_id == user_id)).all()
    return {"evidence_replayed": len(rows), "concepts": len(concepts)}


# --- Reading it back ------------------------------------------------------------------


def mastery_row_view(row: Mastery) -> dict[str, Any]:
    return {
        "concept_id": row.concept_id,
        "ability": row.ability,
        "normalized_ability": normalized_ability(row.ability),
        "observations": row.observations,
        "calibrating": is_calibrating(row.observations),
        "stability_days": row.stability,
        "due_at": row.due_at,
        "last_seen": row.last_seen,
    }


def mastery_view(db: Session, user_id: str) -> dict[str, Any]:
    rows = db.exec(
        select(Mastery).where(Mastery.user_id == user_id).order_by(col(Mastery.ability))
    ).all()
    return {
        "concepts": [mastery_row_view(row) for row in rows],
        # Stated because "12 concepts, weakest first" reads very differently once you know
        # the taxonomy has 159 and the rest have never been measured at all.
        "measured": len(rows),
        "calibrating": sum(1 for row in rows if is_calibrating(row.observations)),
    }


def concept_detail(db: Session, user_id: str, concept_id: str) -> dict[str, Any]:
    """One concept, with the evidence rows behind it.

    docs/API.md calls this the feature that makes the adaptive engine auditable: every
    number here traces back to graded artifacts you can re-read.
    """
    row = db.get(Mastery, (user_id, concept_id))
    evidence = db.exec(
        select(ConceptEvidence)
        .where(ConceptEvidence.concept_id == concept_id)
        .order_by(col(ConceptEvidence.ts).desc())
    ).all()
    return {
        "concept_id": concept_id,
        "mastery": mastery_row_view(row) if row is not None else None,
        "evidence": [
            {
                "id": e.id,
                "ts": e.ts,
                "score": e.score,
                "confidence": e.confidence,
                "source": e.source,
                "item_id": e.item_id,
                "session_id": e.session_id,
                "practice_problem_id": e.practice_problem_id,
                "grader_version": e.grader_version,
            }
            for e in evidence
        ],
    }
