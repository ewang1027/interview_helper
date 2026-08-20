"""Mastery routes — what the engine believes, and the evidence it believes it from.

docs/API.md: `GET /mastery/{concept_id}` returning the underlying evidence is what makes
the adaptive engine auditable. `POST /mastery/recompute` exists because `mastery` is a
projection: when a grader bug is found and fixed, the fix is to correct the evidence and
replay, never to hand-patch the number.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from api import mastery as service
from api import priority as priority_weights
from api.auth import CurrentPrincipal
from api.db import get_session
from api.errors import not_found
from api.models import Concept
from api.planner import DOMAIN_FOR_MODE, build_plan
from api.priority import rank_concepts
from api.schemas import Mode

router = APIRouter(tags=["mastery"])

DbSession = Annotated[Session, Depends(get_session)]


@router.get("/mastery")
def get_mastery(db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    """Every concept that has been measured, weakest first."""
    return service.mastery_view(db, principal.user_id)


# Declared before `/mastery/{concept_id}`, and that order is load-bearing: FastAPI
# matches routes in registration order, so the parameterised route would otherwise
# swallow `weaknesses` as a concept id and answer a 404 for a route that exists.
@router.get("/mastery/weaknesses")
def get_weaknesses(
    db: DbSession,
    principal: CurrentPrincipal,
    mode: Annotated[Mode | None, Query()] = None,
    limit: Annotated[int, Query(gt=0, le=100)] = 20,
) -> dict[str, Any]:
    """Ranked weakness list, with the priority terms behind each rank.

    The breakdown is the point: a ranking you cannot take apart is a ranking you cannot
    argue with, and these weights are placeholders waiting for exactly that argument.
    """
    domain = DOMAIN_FOR_MODE[mode] if mode else None
    ranked = rank_concepts(db, principal.user_id, domain=domain)
    return {
        "mode": mode,
        "weights": {
            "weakness": priority_weights.W_ABILITY,
            "recent_errors": priority_weights.W_ERROR,
            "overdue": priority_weights.W_OVERDUE,
            "unlocks": priority_weights.W_UNLOCKS,
            "recent_exposure": priority_weights.W_EXPOSURE,
        },
        "concepts": [entry.as_dict() for entry in ranked[:limit]],
    }


@router.get("/mastery/{concept_id}")
def get_concept(concept_id: str, db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    if db.get(Concept, concept_id) is None:
        raise not_found("concept", concept_id)
    return service.concept_detail(db, principal.user_id, concept_id)


@router.post("/mastery/recompute")
def post_recompute(db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    """Rebuild the projection from `concept_evidence` alone.

    Rebuilds item ratings too — `items.elo` is as much a projection of outcomes as
    `ability` is, and resetting one without the other would leave a state no replay could
    reproduce.
    """
    return service.recompute(db, principal.user_id)


@router.get("/plan/next")
def get_next_plan(
    db: DbSession,
    principal: CurrentPrincipal,
    mode: Annotated[Mode, Query()] = "coding",
    budget_minutes: Annotated[int, Query(gt=0, le=240)] = 45,
) -> dict[str, Any]:
    """What the planner would choose right now, without starting a session.

    Same call `POST /sessions` makes, with nothing written: you should be able to look at
    the next session before committing to it.
    """
    return build_plan(db, principal.user_id, mode, budget_minutes)
