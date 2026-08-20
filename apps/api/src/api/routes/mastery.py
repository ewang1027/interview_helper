"""Mastery routes — what the engine believes, and the evidence it believes it from.

docs/API.md: `GET /mastery/{concept_id}` returning the underlying evidence is what makes
the adaptive engine auditable. `POST /mastery/recompute` exists because `mastery` is a
projection: when a grader bug is found and fixed, the fix is to correct the evidence and
replay, never to hand-patch the number.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from api import mastery as service
from api.db import get_session
from api.errors import not_found
from api.models import Concept
from api.users import current_user

router = APIRouter(tags=["mastery"])

DbSession = Annotated[Session, Depends(get_session)]


@router.get("/mastery")
def get_mastery(db: DbSession) -> dict[str, Any]:
    """Every concept that has been measured, weakest first."""
    return service.mastery_view(db, current_user(db).id)


@router.get("/mastery/{concept_id}")
def get_concept(concept_id: str, db: DbSession) -> dict[str, Any]:
    if db.get(Concept, concept_id) is None:
        raise not_found("concept", concept_id)
    return service.concept_detail(db, current_user(db).id, concept_id)


@router.post("/mastery/recompute")
def post_recompute(db: DbSession) -> dict[str, Any]:
    """Rebuild the projection from `concept_evidence` alone.

    Rebuilds item ratings too — `items.elo` is as much a projection of outcomes as
    `ability` is, and resetting one without the other would leave a state no replay could
    reproduce.
    """
    return service.recompute(db, current_user(db).id)
