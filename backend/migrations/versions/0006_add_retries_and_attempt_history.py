"""Add retries: `retrying` statuses, next-attempt times and the attempt history.

* integration_events: status `retrying`, column `next_attempt_at`, partial index for the
  relay's "which retries are due?" query;
* synchronization_jobs: status `retrying`, column `next_attempt_at`;
* synchronization_attempts: one row per external call made for a job.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# op.f(): the names are final - the naming convention must not prefix them again.
EVENT_CK = op.f("ck_integration_events_integration_event_status")
JOB_CK = op.f("ck_synchronization_jobs_synchronization_job_status")
EVENT_STATUSES = ("pending", "processing", "completed", "failed")
JOB_STATUSES = ("pending", "running", "succeeded", "failed", "skipped")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.drop_constraint(EVENT_CK, "integration_events", type_="check")
    op.create_check_constraint(
        EVENT_CK, "integration_events", _in("status", (*EVENT_STATUSES, "retrying"))
    )
    op.add_column(
        "integration_events",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_integration_events_retrying_next_attempt_at",
        "integration_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'retrying'"),
    )

    op.drop_constraint(JOB_CK, "synchronization_jobs", type_="check")
    op.create_check_constraint(
        JOB_CK, "synchronization_jobs", _in("status", (*JOB_STATUSES, "retrying"))
    )
    op.add_column(
        "synchronization_jobs",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_synchronization_jobs_organization_id_id"),
        "synchronization_jobs",
        ["organization_id", "id"],
    )

    op.create_table(
        "synchronization_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "succeeded",
                "failed",
                "skipped",
                "interrupted",
                name="synchronization_attempt_outcome",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("error_category", sa.String(length=30), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("retry_after_seconds", sa.Float(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name=op.f("ck_synchronization_attempts_attempt_number_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["synchronization_jobs.organization_id", "synchronization_jobs.id"],
            name="fk_synchronization_attempts_job_same_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synchronization_attempts")),
        sa.UniqueConstraint(
            "job_id",
            "attempt_number",
            name=op.f("uq_synchronization_attempts_job_id_attempt_number"),
        ),
    )
    op.create_index(
        "ix_synchronization_attempts_organization_id_started_at",
        "synchronization_attempts",
        ["organization_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_synchronization_attempts_organization_id_started_at",
        table_name="synchronization_attempts",
    )
    op.drop_table("synchronization_attempts")

    # Rows in the new state become failed: the pre-0006 schema has no retries.
    op.execute("UPDATE synchronization_jobs SET status = 'failed' WHERE status = 'retrying'")
    op.drop_constraint(
        op.f("uq_synchronization_jobs_organization_id_id"), "synchronization_jobs", type_="unique"
    )
    op.drop_column("synchronization_jobs", "next_attempt_at")
    op.drop_constraint(JOB_CK, "synchronization_jobs", type_="check")
    op.create_check_constraint(JOB_CK, "synchronization_jobs", _in("status", JOB_STATUSES))

    op.execute("UPDATE integration_events SET status = 'failed' WHERE status = 'retrying'")
    op.drop_index("ix_integration_events_retrying_next_attempt_at", table_name="integration_events")
    op.drop_column("integration_events", "next_attempt_at")
    op.drop_constraint(EVENT_CK, "integration_events", type_="check")
    op.create_check_constraint(EVENT_CK, "integration_events", _in("status", EVENT_STATUSES))
