"""Cost routes — what has been spent, and what is left to spend.

docs/API.md specified both since Phase 3 and neither existed, because nothing wrote a
ledger row. `GET /costs/budget` is the more useful of the two while the agent is being
built: it answers "will the next call be refused, and why" without making one.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from api import llm, sessions
from api.auth import CurrentPrincipal
from api.db import get_session
from api.settings import Settings, get_settings

router = APIRouter(tags=["costs"])

DbSession = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


@router.get("/costs")
def get_costs(
    db: DbSession,
    principal: CurrentPrincipal,
    days: Annotated[int, Query(gt=0, le=90)] = 7,
) -> dict[str, Any]:
    """Ledger rollups: totals, then by job and by model.

    Split those two ways because they answer different questions — by job says what is
    expensive to do, by model says what the routing table is actually costing.
    """
    return llm.rollup(db, days=days)


@router.get("/costs/budget")
def get_budget(
    db: DbSession,
    principal: CurrentPrincipal,
    settings: Config,
    session_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Remaining session and daily token budget (docs/COST.md's hard limits).

    `session_id` is optional: without one this reports the daily budget only, since a
    per-session remainder needs a session to be about. When given, it is resolved through
    `sessions.get_session` first — docs/API.md says both routes are "scoped by the session
    cookie like everything else under `/api/v1`", and this one alone took the parameter on
    trust, answering 200 with another principal's spend for an id that `GET /sessions/{id}`
    would 404. Nil impact on a single-user deployment; the inconsistency is the defect.
    """
    if session_id is not None:
        sessions.get_session(db, session_id, user_id=principal.user_id)
    return llm.budget_status(db, session_id=session_id, settings=settings)
