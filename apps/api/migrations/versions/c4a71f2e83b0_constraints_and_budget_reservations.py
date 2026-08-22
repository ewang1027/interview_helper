"""Unique constraints on the read-then-write paths, and budget reservations.

Five audit findings, one shape: a check that reads, decides, and writes with nothing
between the read and the write. Serially each is correct; overlapped, each one loses.

- `artifacts(session_id, item_id)` — two concurrent submissions for one item both passed
  the "already submitted" check, stored two artifacts, ran two gradings and wrote eight
  `concept_evidence` rows for four concepts. Evidence is immutable and the projection
  replays it faithfully, so the double-count is permanent.
- `turns(session_id, seq)` — `agent.loop.next_seq` is `max(seq) + 1`, so two concurrent
  turns take the same number and the transcript's order stops being recoverable.
- `practice_solves(problem_id, review_number)` — two concurrent reviews collided on
  `review_number`, one `solve_count` update was lost, and the problem never graduated.

The reservation columns on `llm_calls` fix the one that costs money. `enforce_budget` read
the ledger in a transaction that closed before the provider was called, so overlapping
calls all saw the same pre-spend total. Measured: eight concurrent calls against a
1000-token daily ceiling all proceeded, spending 8,000,000 tokens — an 8000x overshoot of
a limit `docs/COST.md` describes as bounded by one call's `max_tokens`.

A row is now written *before* the call, holding what the call may cost, and settled with
the real usage after. That also closes a second finding: a streamed call that dropped
after the provider had already produced output left no ledger row at all, because the
row was only ever written on success.

Revision ID: c4a71f2e83b0
Revises: b9aeed88a3bd
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a71f2e83b0"
down_revision: str | Sequence[str] | None = "b9aeed88a3bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing duplicates would make the constraint un-creatable. There are none in any
    # database this has run against, but a migration that assumes that and fails halfway
    # is worse than one that says so — so the duplicates are collapsed first, keeping the
    # earliest row of each group, which is the one whose grading the projection already
    # reflects.
    op.execute(
        """
        DELETE FROM artifacts a USING artifacts b
        WHERE a.session_id = b.session_id AND a.item_id = b.item_id AND a.id > b.id
        """
    )
    op.execute(
        """
        DELETE FROM turns a USING turns b
        WHERE a.session_id = b.session_id AND a.seq = b.seq AND a.id > b.id
        """
    )
    op.execute(
        """
        DELETE FROM practice_solves a USING practice_solves b
        WHERE a.problem_id = b.problem_id AND a.review_number = b.review_number AND a.id > b.id
        """
    )

    op.create_unique_constraint(
        "artifacts_session_item_unique", "artifacts", ["session_id", "item_id"]
    )
    op.create_unique_constraint("turns_session_seq_unique", "turns", ["session_id", "seq"])
    op.create_unique_constraint(
        "practice_solves_number_unique", "practice_solves", ["problem_id", "review_number"]
    )

    # `status` defaults to 'settled' so every existing row keeps meaning exactly what it
    # meant: a call that completed and was billed.
    op.add_column(
        "llm_calls",
        sa.Column("status", sa.String(), nullable=False, server_default="settled"),
    )
    op.add_column(
        "llm_calls",
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("llm_calls", sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True))
    # Enforcement filters on (status, created_at) on every model call.
    op.create_index("ix_llm_calls_status_created", "llm_calls", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_status_created", table_name="llm_calls")
    op.drop_column("llm_calls", "settled_at")
    op.drop_column("llm_calls", "reserved_tokens")
    op.drop_column("llm_calls", "status")
    op.drop_constraint("practice_solves_number_unique", "practice_solves", type_="unique")
    op.drop_constraint("turns_session_seq_unique", "turns", type_="unique")
    op.drop_constraint("artifacts_session_item_unique", "artifacts", type_="unique")
