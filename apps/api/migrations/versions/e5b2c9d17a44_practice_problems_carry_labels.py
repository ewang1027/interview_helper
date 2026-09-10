"""Practice problems carry labels of your own.

The practice log classifies every problem against the concept taxonomy, and that is the
right axis for mastery — it is what the evidence is keyed on. It is not the only axis a
person files problems by. "Blind 75", "Jane Street", "redo before the onsite", "got it
without hints" are all real categories, none of them is a concept, and none of them
belongs in the taxonomy, which is a build-time artifact with a validator.

So: one JSONB array of free-text labels per problem, owned entirely by the person, never
read by anything that writes evidence. Default `[]` and `NOT NULL`, so a row is never in
the state of "has no labels" versus "labels unknown".

Revision ID: e5b2c9d17a44
Revises: d4f81c07b6a3
Create Date: 2026-09-10 00:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5b2c9d17a44"
down_revision: str | Sequence[str] | None = "d4f81c07b6a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "practice_problems",
        sa.Column(
            "labels",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("practice_problems", "labels")
