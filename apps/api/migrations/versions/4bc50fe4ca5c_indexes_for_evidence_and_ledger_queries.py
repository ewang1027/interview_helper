"""Index `concept_evidence` and `llm_calls` on the columns their queries filter by.

Both tables are append-only and grow with use, and every query below was a sequential scan.
That cost nothing at today's size and grows without limit.

**`concept_evidence`** had the primary key and `(concept_id)`, and nothing else:

- `(session_id, item_id, concept_id, ts, id)` serves the "first grading of this attempt"
  lookup `mastery.apply_evidence` runs for every primary-concept grading: three equalities,
  then the order it sorts by. Its leading column also serves the session report and the
  planner's exposure term, which filter on `session_id`.
- `(practice_problem_id)` serves the practice problem detail that every practice write
  returns.
- `(concept_id)` becomes `(concept_id, ts DESC, id DESC)`. That is the order the planner's
  five-newest-per-concept window and the concept detail page read in. The leading column
  still serves everything the old index did.

**`llm_calls`** had only `(status, created_at)`. The budget totals filter on
`created_at >= since` or `session_id = ?`, with `status` inside a `CASE`, so a leading
`status` column was no use to them. The comment on the model that said otherwise was
wrong. `(created_at)` and `(session_id)` are added. The composite stays, because the
reservation sweep filters on both of its columns.

Revision ID: 4bc50fe4ca5c
Revises: e5b2c9d17a44
Create Date: 2026-10-10 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "4bc50fe4ca5c"
down_revision: str | Sequence[str] | None = "e5b2c9d17a44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_concept_evidence_attempt",
        "concept_evidence",
        ["session_id", "item_id", "concept_id", "ts", "id"],
    )
    op.create_index(
        "ix_concept_evidence_practice_problem", "concept_evidence", ["practice_problem_id"]
    )
    op.drop_index("ix_concept_evidence_concept_id", table_name="concept_evidence")
    op.execute(
        "CREATE INDEX ix_concept_evidence_concept_newest "
        "ON concept_evidence (concept_id, ts DESC, id DESC)"
    )
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"])
    op.create_index("ix_llm_calls_session_id", "llm_calls", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_session_id", table_name="llm_calls")
    op.drop_index("ix_llm_calls_created_at", table_name="llm_calls")
    op.drop_index("ix_concept_evidence_concept_newest", table_name="concept_evidence")
    op.create_index("ix_concept_evidence_concept_id", "concept_evidence", ["concept_id"])
    op.drop_index("ix_concept_evidence_practice_problem", table_name="concept_evidence")
    op.drop_index("ix_concept_evidence_attempt", table_name="concept_evidence")
