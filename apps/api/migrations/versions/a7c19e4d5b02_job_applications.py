"""The job-application tracker, and the web searches its research pass bills for.

Two tables, split the way `mastery` and `concept_evidence` are: `job_application_events`
is append-only and records every stage an application was ever in, and the three
projection columns on `job_applications` — `current_stage`, `furthest_stage`, `outcome` —
are what those events add up to. `api.jobs.recompute` rebuilds all three from the events
alone, so the funnel is derived rather than remembered.

`furthest_stage` is the column that makes the funnel honest. A rejection after an onsite
sets `current_stage` to `rejected`; without a separate high-water mark, that application
would silently leave the "reached final round" bucket and the conversion rates would
improve every time something went wrong.

`llm_calls.web_search_requests` rides along because the research pass is the first call in
this project to use a **server-side tool**, and web search is billed per search
($10/1,000) on top of the tokens the results consume. A ledger that counts only tokens
under-reports that call by the one component `usage.*_tokens` does not carry — and with a
$1 session ceiling, thirty uncounted searches is a third of it. `server_default="0"` so
every settled row already on the ledger backfills correctly: none of them declared a
server tool, so none of them made a search.

Revision ID: a7c19e4d5b02
Revises: efbc34ba6da0
Create Date: 2026-08-25 20:14:11.402117
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c19e4d5b02"
down_revision: str | Sequence[str] | None = "efbc34ba6da0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_applications",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("subcategory", sa.String(), nullable=True),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("classification_model", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending_classification"),
        sa.Column("current_stage", sa.String(), nullable=False, server_default="applied"),
        sa.Column("furthest_stage", sa.String(), nullable=False, server_default="applied"),
        sa.Column("outcome", sa.String(), nullable=False, server_default="open"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "company", "role", name="job_applications_company_role_unique"
        ),
    )
    op.create_index("ix_job_applications_user_id", "job_applications", ["user_id"])
    op.create_index(
        "ix_job_applications_stage", "job_applications", ["current_stage", "updated_at"]
    )

    op.create_table(
        "job_application_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["job_applications.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", "sequence", name="job_application_events_seq_unique"),
    )
    op.create_index(
        "ix_job_application_events_application_id", "job_application_events", ["application_id"]
    )

    op.add_column(
        "llm_calls",
        sa.Column("web_search_requests", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("llm_calls", "web_search_requests")
    op.drop_index("ix_job_application_events_application_id", table_name="job_application_events")
    op.drop_table("job_application_events")
    op.drop_index("ix_job_applications_stage", table_name="job_applications")
    op.drop_index("ix_job_applications_user_id", table_name="job_applications")
    op.drop_table("job_applications")
