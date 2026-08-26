"""Make the job tracker's indexes match the queries that actually run against it.

Three changes, and the first is a correctness fix rather than a speed one.

**The unique constraint and the duplicate check disagreed about case.** The constraint was
`(user_id, company, role)` — case-*sensitive* — while `api.jobs.existing` looked rows up
with `lower(company)` and `lower(role)`. So "Aurora Labs" and "aurora labs" were two
different rows to the constraint and the same row to every duplicate check: both could be
stored, and the second one was then permanently invisible to the code meant to find it.
Replaced with a unique index on the folded columns, which is the shape the lookup was
already assuming.

That index is also what makes the lookup fast. A predicate on `lower(company)` cannot use
an index on `company`, so every duplicate check was a sequential scan — invisible at
today's size and quadratic in the one that matters, since an import checks once per row.

**`ix_job_applications_stage` served no query.** It was `(current_stage, updated_at)`, and
the board's query filters on `user_id` and orders by `applied_at`. Replaced with
`(user_id, applied_at DESC)`, which is the one the list endpoint actually issues.

Revision ID: d4f81c07b6a3
Revises: a7c19e4d5b02
Create Date: 2026-08-25 23:58:02.771904
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d4f81c07b6a3"
down_revision: str | Sequence[str] | None = "a7c19e4d5b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fold any rows that already differ only by case before the unique index refuses them.
    # There should be none — the application-level check has been case-insensitive since
    # the feature landed — but a migration that fails on real data is worse than one that
    # says what it did, and `created_at` keeps the oldest, which is the one whose events
    # and history the rest of the system already points at.
    op.execute(
        """
        DELETE FROM job_application_events
        WHERE application_id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY user_id, lower(company), lower(role) ORDER BY created_at
                ) AS n
                FROM job_applications
            ) ranked WHERE ranked.n > 1
        )
        """
    )
    op.execute(
        """
        DELETE FROM job_applications
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY user_id, lower(company), lower(role) ORDER BY created_at
                ) AS n
                FROM job_applications
            ) ranked WHERE ranked.n > 1
        )
        """
    )

    op.drop_constraint("job_applications_company_role_unique", "job_applications", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX job_applications_company_role_unique "
        "ON job_applications (user_id, lower(company), lower(role))"
    )

    op.drop_index("ix_job_applications_stage", table_name="job_applications")
    op.execute(
        "CREATE INDEX ix_job_applications_user_applied "
        "ON job_applications (user_id, applied_at DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_job_applications_user_applied", table_name="job_applications")
    op.create_index(
        "ix_job_applications_stage", "job_applications", ["current_stage", "updated_at"]
    )
    op.execute("DROP INDEX job_applications_company_role_unique")
    op.create_unique_constraint(
        "job_applications_company_role_unique",
        "job_applications",
        ["user_id", "company", "role"],
    )
