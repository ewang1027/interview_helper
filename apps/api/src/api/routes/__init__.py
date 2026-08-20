"""The `/api/v1` surface.

docs/API.md called the move under a version prefix "owed when the router lands"; this is
that router. `/health` deliberately stays at the root: it is what a load balancer and an
ECS task health check will poll (docs/INFRA.md), and the auth that eventually guards
everything under `/api/v1` is documented as excluding it — keeping it outside the prefix
makes that exclusion structural rather than a special case inside an auth dependency.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.routes import corpus, sessions

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(corpus.router)
api_v1.include_router(sessions.router)

__all__ = ["api_v1"]
