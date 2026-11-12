"""Add data integrity: source-of-truth policies, conflicts and resolutions.

* data_source_policies: per organization and field, which side is authoritative
  (SyncForge or one connector), the severity and the resolution mode;
* data_conflicts: one row per (employee, connector, field) disagreement, at most one open
  (partial unique index), with both values, authority and severity at detection;
* conflict_resolutions: the decision history.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIELD_CHECK = (
    "field IN ('first_name', 'last_name', 'email', 'department', 'designation', "
    "'location', 'account_active')"
)


def upgrade() -> None:
    op.create_table(
        "data_source_policies",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=30), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "syncforge",
                "connector",
                name="policy_source",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("connector_id", sa.Uuid(), nullable=True),
        sa.Column(
            "resolution_mode",
            sa.Enum(
                "manual",
                "auto",
                name="resolution_mode",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "low",
                "medium",
                "high",
                "critical",
                name="conflict_severity",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "(source = 'connector') = (connector_id IS NOT NULL)",
            name=op.f("ck_data_source_policies_connector_iff_source"),
        ),
        sa.CheckConstraint(
            FIELD_CHECK,
            name=op.f("ck_data_source_policies_field"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_data_source_policies_connector_same_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_data_source_policies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_source_policies")),
        sa.UniqueConstraint(
            "organization_id", "field", name=op.f("uq_data_source_policies_organization_id_field")
        ),
    )
    op.create_table(
        "data_conflicts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=30), nullable=False),
        sa.Column("syncforge_value", sa.String(length=320), nullable=True),
        sa.Column("external_value", sa.String(length=320), nullable=True),
        sa.Column(
            "authoritative_source",
            sa.Enum(
                "syncforge",
                "connector",
                name="policy_source",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "low",
                "medium",
                "high",
                "critical",
                name="conflict_severity",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "resolved",
                "dismissed",
                name="conflict_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("employee_version", sa.Integer(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("times_detected", sa.Integer(), server_default="1", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            FIELD_CHECK,
            name=op.f("ck_data_conflicts_field"),
        ),
        sa.CheckConstraint(
            "times_detected >= 1", name=op.f("ck_data_conflicts_times_detected_positive")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_data_conflicts_connector_same_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "employee_id"],
            ["employees.organization_id", "employees.id"],
            name="fk_data_conflicts_employee_same_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_conflicts")),
    )
    op.create_index(
        "ix_data_conflicts_organization_id_status",
        "data_conflicts",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_data_conflicts_open_employee_connector_field",
        "data_conflicts",
        ["employee_id", "connector_id", "field"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "conflict_resolutions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("conflict_id", sa.Uuid(), nullable=False),
        sa.Column(
            "resolution",
            sa.Enum(
                "use_syncforge",
                "use_external",
                "dismiss",
                "no_longer_different",
                name="resolution_kind",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("applied_value", sa.String(length=320), nullable=True),
        sa.Column("against_policy", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("automatic", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conflict_id"],
            ["data_conflicts.id"],
            name=op.f("fk_conflict_resolutions_conflict_id_data_conflicts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            name=op.f("fk_conflict_resolutions_resolved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conflict_resolutions")),
    )
    op.create_index(
        "ix_conflict_resolutions_conflict_id", "conflict_resolutions", ["conflict_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_conflict_resolutions_conflict_id", table_name="conflict_resolutions")
    op.drop_table("conflict_resolutions")
    op.drop_index(
        "uq_data_conflicts_open_employee_connector_field",
        table_name="data_conflicts",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.drop_index("ix_data_conflicts_organization_id_status", table_name="data_conflicts")
    op.drop_table("data_conflicts")
    op.drop_table("data_source_policies")
