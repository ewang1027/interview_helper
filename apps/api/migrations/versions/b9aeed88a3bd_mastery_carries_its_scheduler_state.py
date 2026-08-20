"""mastery carries its scheduler state

The projection has to be able to *advance* a schedule, not just report one. FSRS needs a
card's difficulty, state and step to compute the next interval, and `mastery` exposed only
`stability` and `due_at` — the two numbers worth querying. `fsrs_card` stores the
scheduler's own serialised card so an update is incremental; a library upgrade that
changes that shape is recovered by `POST /mastery/recompute`, not by a migration.

`observations` is what decays the Elo K-factor: early evidence moves an estimate fast,
later evidence refines it (docs/ADAPTIVE.md). Added with a server default so the column
can be NOT NULL, then dropped, so every write states the count explicitly.

Revision ID: b9aeed88a3bd
Revises: 137646f0d9a1
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b9aeed88a3bd"
down_revision: str | Sequence[str] | None = "137646f0d9a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mastery", sa.Column("observations", sa.Integer(), nullable=False, server_default="0")
    )
    op.alter_column("mastery", "observations", server_default=None)
    op.add_column(
        "mastery", sa.Column("fsrs_card", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("mastery", "fsrs_card")
    op.drop_column("mastery", "observations")
