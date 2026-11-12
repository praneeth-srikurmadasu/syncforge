"""Add the dead-letter queue.

* integration_events: status `failed` becomes `dead_letter`; unique (organization_id, id)
  as the target of the queue's composite foreign key;
* synchronization_jobs: `attempts_at_last_replay` (retry budget per replay round);
* dead_letter_events: one entry per event that failed for good, with its error copied.

Existing `failed` events are moved to `dead_letter` and get an entry built from their
first failed step, so nothing that failed before this migration is lost from view.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENT_CK = op.f("ck_integration_events_integration_event_status")
OLD_EVENT_STATUSES = ("pending", "processing", "retrying", "completed", "failed")
NEW_EVENT_STATUSES = ("pending", "processing", "retrying", "completed", "dead_letter")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


# One entry per failed event, from its first failed job (execution order, then step
# position) and that job's last attempt.
BACKFILL = """
INSERT INTO dead_letter_events (
    id, organization_id, event_id, reason, job_id, connector_id, operation,
    error_category, error_code, http_status, error_message, attempts, failed_steps,
    dead_lettered_at, status
)
SELECT
    gen_random_uuid(), e.organization_id, e.id,
    CASE WHEN a.retryable THEN 'retries_exhausted' ELSE 'non_retryable' END,
    j.id, j.connector_id, j.operation, j.error_category, a.error_code, a.http_status,
    COALESCE(j.error_message, e.last_error), COALESCE(j.attempts, 0),
    GREATEST(
        (SELECT count(*) FROM synchronization_jobs fj
           JOIN workflow_executions fx ON fx.id = fj.execution_id
          WHERE fx.event_id = e.id AND fj.status = 'failed'),
        1
    ),
    COALESCE(e.completed_at, e.updated_at), 'open'
FROM integration_events e
LEFT JOIN LATERAL (
    SELECT sj.* FROM synchronization_jobs sj
    JOIN workflow_executions x ON x.id = sj.execution_id
    WHERE x.event_id = e.id AND sj.status = 'failed'
    ORDER BY x.created_at, x.id, sj.position
    LIMIT 1
) j ON true
LEFT JOIN LATERAL (
    SELECT sa.* FROM synchronization_attempts sa
    WHERE sa.job_id = j.id
    ORDER BY sa.attempt_number DESC
    LIMIT 1
) a ON true
WHERE e.status = 'failed'
"""


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_integration_events_organization_id_id"),
        "integration_events",
        ["organization_id", "id"],
    )
    op.add_column(
        "synchronization_jobs",
        sa.Column("attempts_at_last_replay", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_synchronization_jobs_replay_offset_valid"),
        "synchronization_jobs",
        "attempts_at_last_replay BETWEEN 0 AND attempts",
    )

    op.create_table(
        "dead_letter_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "reason",
            _enum("retries_exhausted", "non_retryable", name="dead_letter_reason"),
            nullable=False,
        ),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("connector_id", sa.Uuid(), nullable=True),
        sa.Column("operation", sa.String(length=30), nullable=True),
        sa.Column("error_category", sa.String(length=30), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_steps", sa.Integer(), server_default="1", nullable=False),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            _enum("open", "replayed", name="dead_letter_status"),
            server_default="open",
            nullable=False,
        ),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replayed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "event_id"],
            ["integration_events.organization_id", "integration_events.id"],
            name="fk_dead_letter_events_event_same_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["synchronization_jobs.organization_id", "synchronization_jobs.id"],
            name="fk_dead_letter_events_job_same_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replayed_by_user_id"],
            ["users.id"],
            name=op.f("fk_dead_letter_events_replayed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dead_letter_events")),
    )
    op.create_index(
        "uq_dead_letter_events_open_event_id",
        "dead_letter_events",
        ["event_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_dead_letter_events_organization_id_status_dead_lettered_at",
        "dead_letter_events",
        ["organization_id", "status", "dead_lettered_at"],
    )

    op.drop_constraint(EVENT_CK, "integration_events", type_="check")
    op.execute(BACKFILL)
    op.execute("UPDATE integration_events SET status = 'dead_letter' WHERE status = 'failed'")
    op.create_check_constraint(EVENT_CK, "integration_events", _in("status", NEW_EVENT_STATUSES))


def downgrade() -> None:
    op.drop_constraint(EVENT_CK, "integration_events", type_="check")
    op.execute("UPDATE integration_events SET status = 'failed' WHERE status = 'dead_letter'")
    op.create_check_constraint(EVENT_CK, "integration_events", _in("status", OLD_EVENT_STATUSES))

    op.drop_index(
        "ix_dead_letter_events_organization_id_status_dead_lettered_at",
        table_name="dead_letter_events",
    )
    op.drop_index("uq_dead_letter_events_open_event_id", table_name="dead_letter_events")
    op.drop_table("dead_letter_events")
    op.drop_constraint(
        op.f("ck_synchronization_jobs_replay_offset_valid"), "synchronization_jobs", type_="check"
    )
    op.drop_column("synchronization_jobs", "attempts_at_last_replay")
    op.drop_constraint(
        op.f("uq_integration_events_organization_id_id"), "integration_events", type_="unique"
    )
