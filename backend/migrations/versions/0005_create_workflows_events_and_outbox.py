"""Create workflows, integration events, the transactional outbox and executions.

* workflows / workflow_steps: administrator-configured automations (trigger + ordered
  connector operations);
* integration_events: durable employee events with their processing status;
* outbox_events: rows the relay publishes to the message broker (written in the same
  transaction as the employee change and its event);
* workflow_executions / synchronization_jobs: one execution per (event, workflow) and
  one job per step, with per-step status.

Every child references its parent through composite (organization_id, id) foreign keys,
so no row can point into another organization.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGERS = (
    "employee.created",
    "employee.updated",
    "employee.department_changed",
    "employee.manager_changed",
    "employee.terminated",
)
OPERATIONS = ("create_user", "update_user", "deactivate_user")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _status(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _same_org_fk(
    name: str, column: str, target: str, *, cascade: bool = True, deferred: bool = False
) -> sa.Constraint:
    """Composite (organization_id, <column>) -> <target>(organization_id, id)."""
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{target}.organization_id", f"{target}.id"],
        name=name,
        ondelete="CASCADE" if cascade else None,
        deferrable=deferred or None,
        initially="DEFERRED" if deferred else None,
    )


def upgrade() -> None:
    op.create_table(
        "workflows",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("trigger_event_type", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            _in_list("trigger_event_type", TRIGGERS), name=op.f("ck_workflows_trigger")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_workflows_version_positive")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_workflows_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_workflows_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_workflows_organization_id_name")
        ),
    )
    op.create_index(
        "ix_workflows_organization_id_trigger_event_type",
        "workflows",
        ["organization_id", "trigger_event_type"],
    )

    op.create_table(
        "workflow_steps",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            _in_list("operation", OPERATIONS), name=op.f("ck_workflow_steps_operation")
        ),
        sa.CheckConstraint("position >= 1", name=op.f("ck_workflow_steps_position_positive")),
        _same_org_fk("fk_workflow_steps_workflow_same_organization", "workflow_id", "workflows"),
        # No ON DELETE action: a connector in use by a workflow cannot be deleted. Checked
        # at commit, so an organization delete (which cascades to both) is not refused.
        _same_org_fk(
            "fk_workflow_steps_connector_same_organization",
            "connector_id",
            "connectors",
            cascade=False,
            deferred=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_steps")),
        sa.UniqueConstraint(
            "workflow_id", "position", name=op.f("uq_workflow_steps_workflow_id_position")
        ),
    )
    op.create_index("ix_workflow_steps_connector_id", "workflow_steps", ["connector_id"])

    op.create_table(
        "integration_events",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            _status("integration_event_status", "pending", "processing", "completed", "failed"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_integration_events_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "employee_id"],
            ["employees.organization_id", "employees.id"],
            name="fk_integration_events_employee_same_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_events")),
    )
    op.create_index("ix_integration_events_employee_id", "integration_events", ["employee_id"])
    op.create_index(
        "ix_integration_events_organization_id_created_at",
        "integration_events",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_integration_events_organization_id_status",
        "integration_events",
        ["organization_id", "status"],
    )
    op.create_index(
        "ix_integration_events_unfinished_locked_until",
        "integration_events",
        ["locked_until"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["integration_events.id"],
            name=op.f("fk_outbox_events_event_id_integration_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )

    op.create_table(
        "workflow_executions",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _status("workflow_execution_status", "running", "succeeded", "failed"),
            server_default="running",
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["integration_events.id"],
            name="fk_workflow_executions_event_id_integration_events",
            ondelete="CASCADE",
        ),
        _same_org_fk(
            "fk_workflow_executions_workflow_same_organization", "workflow_id", "workflows"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_executions")),
        sa.UniqueConstraint(
            "event_id", "workflow_id", name=op.f("uq_workflow_executions_event_id_workflow_id")
        ),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_workflow_executions_organization_id_id")
        ),
    )
    op.create_index(
        "ix_workflow_executions_organization_id_workflow_id_created_at",
        "workflow_executions",
        ["organization_id", "workflow_id", "created_at"],
    )

    op.create_table(
        "synchronization_jobs",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            _status(
                "synchronization_job_status",
                "pending",
                "running",
                "succeeded",
                "failed",
                "skipped",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("error_category", sa.String(length=30), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            _in_list("operation", OPERATIONS), name=op.f("ck_synchronization_jobs_operation")
        ),
        sa.CheckConstraint("position >= 1", name=op.f("ck_synchronization_jobs_position_positive")),
        _same_org_fk(
            "fk_synchronization_jobs_execution_same_organization",
            "execution_id",
            "workflow_executions",
        ),
        _same_org_fk(
            "fk_synchronization_jobs_connector_same_organization", "connector_id", "connectors"
        ),
        _same_org_fk(
            "fk_synchronization_jobs_employee_same_organization", "employee_id", "employees"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_synchronization_jobs")),
        sa.UniqueConstraint(
            "execution_id", "position", name=op.f("uq_synchronization_jobs_execution_id_position")
        ),
    )
    op.create_index(
        "ix_synchronization_jobs_connector_id", "synchronization_jobs", ["connector_id"]
    )
    op.create_index(
        "ix_synchronization_jobs_organization_id_status",
        "synchronization_jobs",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_synchronization_jobs_organization_id_status", table_name="synchronization_jobs"
    )
    op.drop_index("ix_synchronization_jobs_connector_id", table_name="synchronization_jobs")
    op.drop_table("synchronization_jobs")
    op.drop_index(
        "ix_workflow_executions_organization_id_workflow_id_created_at",
        table_name="workflow_executions",
    )
    op.drop_table("workflow_executions")
    op.drop_index("ix_outbox_events_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_integration_events_unfinished_locked_until", table_name="integration_events")
    op.drop_index("ix_integration_events_organization_id_status", table_name="integration_events")
    op.drop_index(
        "ix_integration_events_organization_id_created_at", table_name="integration_events"
    )
    op.drop_index("ix_integration_events_employee_id", table_name="integration_events")
    op.drop_table("integration_events")
    op.drop_index("ix_workflow_steps_connector_id", table_name="workflow_steps")
    op.drop_table("workflow_steps")
    op.drop_index("ix_workflows_organization_id_trigger_event_type", table_name="workflows")
    op.drop_table("workflows")
