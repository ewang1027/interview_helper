"""A dollar reservation on the ledger, so the ceilings can be money.

The token ceilings stopped being a proxy for spend the moment the routing table held more
than one model: 3,000,000 tokens is about $15 of Haiku input or $75 of Opus 5 output.
`reserved_usd` is the dollar twin of `reserved_tokens` — what a call may cost if it runs to
its limit, priced at that row's own model, counted against the budget while it is in flight
and zeroed when the row settles with a real `cost_usd`.

Stored rather than derived: `reserved_tokens` is one number and pricing needs the input and
output halves separately, since output costs five times input. `server_default="0"` so the
rows already on the ledger backfill to zero, which is correct — every one of them is
settled and carries a real cost.

Revision ID: efbc34ba6da0
Revises: bf9f6a8ae332
Create Date: 2026-08-25 19:27:04.133885
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "efbc34ba6da0"
down_revision: str | Sequence[str] | None = "bf9f6a8ae332"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_calls", sa.Column("reserved_usd", sa.Float(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("llm_calls", "reserved_usd")
