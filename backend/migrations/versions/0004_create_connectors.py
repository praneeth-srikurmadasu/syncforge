"""Create connectors, connector credentials and external accounts.

Credentials are stored encrypted in their own table and reference their connector
through a composite foreign key on (organization_id, connector_id), so they can never
be attached to another organization's connector. External accounts link an employee to
the user ID an external application assigned, with the same same-organization keys.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def upgrade() -> None:
    op.create_table(
        "connectors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connector_type", sa.String(length=50), nullable=False),
        sa.Column("connector_version", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "connected",
                "error",
                "disconnected",
                name="connector_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_category", sa.String(length=30), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_connectors_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connectors")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_connectors_organization_id_id")),
        sa.UniqueConstraint(
            "organization_id", "name", name=op.f("uq_connectors_organization_id_name")
        ),
    )
    op.create_index(
        "ix_connectors_organization_id_connector_type",
        "connectors",
        ["organization_id", "connector_type"],
    )

    op.create_table(
        "connector_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("auth_type", sa.String(length=40), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_connector_credentials_connector_same_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_credentials")),
        sa.UniqueConstraint("connector_id", name=op.f("uq_connector_credentials_connector_id")),
    )

    op.create_table(
        "external_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "deactivated",
                name="external_account_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_external_accounts_connector_same_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "employee_id"],
            ["employees.organization_id", "employees.id"],
            name="fk_external_accounts_employee_same_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_accounts")),
        sa.UniqueConstraint(
            "connector_id",
            "employee_id",
            name=op.f("uq_external_accounts_connector_id_employee_id"),
        ),
        sa.UniqueConstraint(
            "connector_id",
            "external_id",
            name=op.f("uq_external_accounts_connector_id_external_id"),
        ),
    )
    op.create_index(
        "ix_external_accounts_organization_id_employee_id",
        "external_accounts",
        ["organization_id", "employee_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_accounts_organization_id_employee_id", table_name="external_accounts"
    )
    op.drop_table("external_accounts")
    op.drop_table("connector_credentials")
    op.drop_index("ix_connectors_organization_id_connector_type", table_name="connectors")
    op.drop_table("connectors")
