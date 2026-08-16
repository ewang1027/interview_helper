"""Engine and session dependency.

`apps/api` is the only service with a database connection — see
docs/SECURITY.md's trust boundary. Sync psycopg3, matching the driver already
pinned in pyproject.toml and the `postgresql+psycopg://` scheme in `.env.example`.
"""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlmodel import Session, create_engine

from api.settings import get_settings


@lru_cache
def get_engine():  # type: ignore[no-untyped-def]
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
