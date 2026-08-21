"""The `/api/v1` surface.

docs/API.md called the move under a version prefix "owed when the router lands"; this is
that router. `/health` deliberately stays at the root: it is what a load balancer and an
ECS task health check will poll (docs/INFRA.md), and the auth that guards everything under
`/api/v1` excludes it — keeping it outside the prefix makes that exclusion structural
rather than a special case inside an auth dependency. `/auth/*` is outside for the same
reason: the routes that issue a session cannot require one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import require_principal
from api.routes import corpus, costs, events, mastery, sessions

# One dependency on the router rather than one per route, so a route added later without
# auth is impossible rather than merely unlikely. A per-route decorator is a thing you can
# forget; a prefix is not.
api_v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(require_principal)])
api_v1.include_router(corpus.router)
api_v1.include_router(costs.router)
api_v1.include_router(events.router)
api_v1.include_router(mastery.router)
api_v1.include_router(sessions.router)

__all__ = ["api_v1"]
