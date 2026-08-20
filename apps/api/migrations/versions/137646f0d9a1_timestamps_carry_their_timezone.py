"""timestamps carry their timezone

Every timestamp column becomes `TIMESTAMP WITH TIME ZONE`. They were written as naive
`TIMESTAMP`, so an aware UTC value went in and a naive one came back — which raised the
moment `GET /sessions/{id}` subtracted one from `datetime.now(UTC)` to report elapsed
time. That was the lucky failure. The unlucky one is Phase 4's FSRS scheduling, where two
naive values subtract cleanly and silently mean whatever the server's clock was set to.
docs/API.md promises RFC 3339 UTC with `Z`.

`USING <col> AT TIME ZONE 'UTC'` is explicit on purpose. Without it Postgres interprets
existing values in the *session's* TimeZone setting, so the same migration would produce
different data on a machine that is not UTC — every existing row was written as UTC, and
this states that rather than inheriting it from an environment variable.

Revision ID: 137646f0d9a1
Revises: 1408f9143d32
Create Date: 2026-08-20 17:53:58.017699
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "137646f0d9a1"
down_revision: str | Sequence[str] | None = "1408f9143d32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, nullable) — every datetime column in the schema.
COLUMNS: list[tuple[str, str, bool]] = [
    ("artifacts", "created_at", False),
    ("concept_evidence", "ts", False),
    ("concepts", "deprecated_at", True),
    ("gradings", "created_at", False),
    ("items", "created_at", False),
    ("items", "deprecated_at", True),
    ("llm_calls", "created_at", False),
    ("mastery", "due_at", True),
    ("mastery", "last_seen", True),
    ("practice_problems", "due_at", True),
    ("practice_problems", "graduated_at", True),
    ("practice_problems", "created_at", False),
    ("practice_problems", "updated_at", False),
    ("practice_solves", "attempted_at", False),
    ("practice_solves", "created_at", False),
    ("research_runs", "started_at", False),
    ("research_runs", "finished_at", True),
    ("sessions", "started_at", False),
    ("sessions", "ended_at", True),
    ("turns", "created_at", False),
    ("users", "created_at", False),
]


def upgrade() -> None:
    for table, column, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=postgresql.TIMESTAMP(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=nullable,
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for table, column, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            type_=postgresql.TIMESTAMP(),
            existing_nullable=nullable,
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
