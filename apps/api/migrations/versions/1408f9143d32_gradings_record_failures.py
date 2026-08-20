"""gradings record failures

docs/GRADING.md's "failure is a failure": a grader crash, timeout or OOM kill must be
recorded as a *failed grading*, never as a zero. The original `gradings.score` was NOT
NULL, which left nowhere to record one — the only options were a fabricated score or no
row at all, and both hide the failure. `status` says what happened, `score` is nullable,
and the CHECK stops the two from disagreeing.

`status` is added with a server default so the column can be NOT NULL on a table that
already has rows; the default is then dropped, because every future write states its
status explicitly and a default would let a caller omit it by accident.

Revision ID: 1408f9143d32
Revises: 6e1d353bc543
Create Date: 2026-08-20 17:45:27.991090
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "1408f9143d32"
down_revision: str | Sequence[str] | None = "6e1d353bc543"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gradings",
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="graded",
        ),
    )
    op.alter_column("gradings", "status", server_default=None)
    op.alter_column(
        "gradings", "score", existing_type=sa.DOUBLE_PRECISION(precision=53), nullable=True
    )
    op.create_check_constraint(
        "gradings_score_present_iff_graded",
        "gradings",
        "(status = 'graded') = (score IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("gradings_score_present_iff_graded", "gradings", type_="check")
    op.execute("DELETE FROM gradings WHERE score IS NULL")
    op.alter_column(
        "gradings", "score", existing_type=sa.DOUBLE_PRECISION(precision=53), nullable=False
    )
    op.drop_column("gradings", "status")
