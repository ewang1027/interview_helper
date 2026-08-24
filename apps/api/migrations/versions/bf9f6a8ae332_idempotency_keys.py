"""Idempotency keys, so a retry is not a second session.

docs/API.md has specified `Idempotency-Key` on `POST /sessions` and `/submissions` since
Phase 3, and listed it as owed *before* the web app "which will retry on flaky networks".
The web app arrived first and sent the header at a server that dropped it.

The composite primary key `(user_id, endpoint, key)` is the mechanism, not a convenience:
two concurrent retries both read no row and both proceed unless the insert itself refuses
the second. Same shape as `artifacts(session_id, item_id)` and `turns(session_id, seq)` in
c4a71f2e83b0, and the same fix — the database decides, because a read-then-write cannot.

Scoped by `user_id` so one caller's key cannot collide with another's, and by `endpoint`
so one key sent to two routes is two keys. `response_json` is nullable because a row
exists while the first request is still running, which is a state a retry is told about
rather than one it can be given an answer for.

Revision ID: bf9f6a8ae332
Revises: c4a71f2e83b0
Create Date: 2026-08-24 14:40:03.868917
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "bf9f6a8ae332"
down_revision: str | Sequence[str] | None = "c4a71f2e83b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("endpoint", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("request_fingerprint", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("response_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("user_id", "endpoint", "key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
