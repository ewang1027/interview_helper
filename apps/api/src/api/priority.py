"""Which concept is worth drilling next, and why.

docs/ADAPTIVE.md's weakness priority, with every term kept separately so the answer can be
*shown* rather than asserted. `GET /mastery/weaknesses` returns this breakdown for the
same reason `POST /sessions` returns its plan: adaptation you cannot inspect is
adaptation you cannot trust — and a weight that turns out to be wrong is only findable if
you can see which term dominated.

```
priority = w1 * (1 - normalized_ability)   # how weak
         + w2 * recent_error_rate          # how weak *lately*
         + w3 * overdue_ratio              # how stale
         + w4 * unlocks                    # how much it blocks downstream
         - w5 * recent_exposure            # anti-repetition
```

**The weights are placeholders.** They are stated in the document as values to calibrate
against real sessions, and no real sessions exist yet. They are named constants rather
than literals in an expression so that calibrating them later is an edit in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from api.mastery import DEFAULT_ABILITY, is_calibrating, normalized_ability
from api.models import Concept, ConceptEdge, ConceptEvidence, InterviewSession, Mastery

W_ABILITY = 0.35
W_ERROR = 0.25
W_OVERDUE = 0.20
W_UNLOCKS = 0.10
W_EXPOSURE = 0.20

# How many recent results count as "lately". Small on purpose: an error rate over all of
# history stops responding to improvement, which is the opposite of what this term is for.
RECENT_RESULTS = 5

# How many recent sessions count as "recently served". The anti-repetition term exists to
# stop the planner serving the same sore spot five sessions running, which is demoralising
# and overfits to a handful of items.
EXPOSURE_SESSIONS = 5

# Above this, an overdue concept contributes its full term. Ten times its own stability is
# far past due by any reading, and without a cap a concept last seen a year ago would swamp
# every other signal forever.
OVERDUE_CAP = 10.0


@dataclass(frozen=True)
class ConceptPriority:
    concept_id: str
    name: str
    domain: str
    priority: float
    ability: float
    observations: int
    calibrating: bool
    unseen: bool
    terms: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "domain": self.domain,
            "priority": self.priority,
            "ability": self.ability,
            "observations": self.observations,
            "calibrating": self.calibrating,
            "unseen": self.unseen,
            "terms": self.terms,
        }


def _overdue_ratio(row: Mastery | None, now: datetime) -> float:
    """How far past due, as a multiple of the concept's own stability."""
    if row is None or row.due_at is None or not row.stability:
        return 0.0
    overdue_days = (now - row.due_at.astimezone(UTC)).total_seconds() / 86_400.0
    if overdue_days <= 0:
        return 0.0
    return min(1.0, overdue_days / (row.stability * OVERDUE_CAP))


def rank_concepts(
    db: Session,
    user_id: str,
    *,
    domain: str | None = None,
    now: datetime | None = None,
) -> list[ConceptPriority]:
    """Every concept in `domain`, most worth drilling first."""
    now = now or datetime.now(UTC)

    concepts = [
        concept
        for concept in db.exec(select(Concept)).all()
        if concept.deprecated_at is None and (domain is None or concept.domain == domain)
    ]
    mastery = {
        entry.concept_id: entry
        for entry in db.exec(select(Mastery).where(Mastery.user_id == user_id)).all()
    }

    # How many concepts each one is a prerequisite for. A weak prerequisite that gates six
    # downstream concepts is worth more than an isolated leaf.
    unlocks: dict[str, int] = {}
    for edge in db.exec(select(ConceptEdge)).all():
        unlocks[edge.prereq_id] = unlocks.get(edge.prereq_id, 0) + 1
    most_unlocks = max(unlocks.values(), default=1)

    # Single user, so every evidence row is theirs — the same simplification
    # `mastery.recompute` already makes. The newest `RECENT_RESULTS` per concept is "lately".
    #
    # Windowed in SQL (2026-10-05). This used to load every evidence row ever written, as
    # full ORM objects sorted by `ts`, and keep five per concept in Python — a cost that grew
    # with history, paid on every plan and every weaknesses read. `id` breaks ties in `ts`,
    # which the old sort left to whatever order Postgres returned.
    newest_first = (
        func.row_number()
        .over(
            partition_by=ConceptEvidence.concept_id,
            order_by=(col(ConceptEvidence.ts).desc(), col(ConceptEvidence.id).desc()),
        )
        .label("newest_first")
    )
    window = (
        select(ConceptEvidence.concept_id, ConceptEvidence.score, newest_first)
        .where(col(ConceptEvidence.concept_id).in_([concept.id for concept in concepts]))
        .subquery()
    )
    recent: dict[str, list[float]] = {}
    for concept_id, score in db.exec(
        select(window.c.concept_id, window.c.score).where(window.c.newest_first <= RECENT_RESULTS)
    ).all():
        recent.setdefault(concept_id, []).append(score)

    recent_session_ids = {
        session_row.id
        for session_row in db.exec(
            select(InterviewSession)
            .where(InterviewSession.user_id == user_id)
            .order_by(col(InterviewSession.id).desc())
            .limit(EXPOSURE_SESSIONS)
        ).all()
    }
    exposure: dict[str, set[str]] = {}
    if recent_session_ids:
        for evidence in db.exec(
            select(ConceptEvidence).where(col(ConceptEvidence.session_id).in_(recent_session_ids))
        ).all():
            if evidence.session_id:
                exposure.setdefault(evidence.concept_id, set()).add(evidence.session_id)

    ranked: list[ConceptPriority] = []
    for concept in concepts:
        measured = mastery.get(concept.id)
        ability = measured.ability if measured else DEFAULT_ABILITY
        observations = measured.observations if measured else 0
        scores = recent.get(concept.id, [])
        # A concept never attempted has no error signal — *not* an error rate of zero
        # meaning "all correct", and not one of 1.0 meaning "all wrong". Leaving the term
        # at zero is what keeps this from conflating never-attempted with attempted-and-
        # failed, which docs/ADAPTIVE.md names as the failure of the obvious approach.
        error_rate = 1.0 - (sum(scores) / len(scores)) if scores else 0.0
        unlock_share = unlocks.get(concept.id, 0) / most_unlocks
        seen_recently = len(exposure.get(concept.id, ())) / EXPOSURE_SESSIONS

        terms = {
            "weakness": W_ABILITY * (1.0 - normalized_ability(ability)),
            "recent_errors": W_ERROR * error_rate,
            "overdue": W_OVERDUE * _overdue_ratio(measured, now),
            "unlocks": W_UNLOCKS * unlock_share,
            "recent_exposure": -W_EXPOSURE * min(1.0, seen_recently),
        }
        ranked.append(
            ConceptPriority(
                concept_id=concept.id,
                name=concept.name,
                domain=concept.domain,
                priority=sum(terms.values()),
                ability=ability,
                observations=observations,
                calibrating=is_calibrating(observations),
                unseen=observations == 0,
                terms=terms,
            )
        )

    ranked.sort(key=lambda entry: (-entry.priority, entry.concept_id))
    return ranked
