"""Add the circuit breaker state and the rate-limit windows, per connector.

* connector_circuits: one row per connector (created on first use) - closed / open /
  half_open, consecutive outage failures, open_until, trial_started_at;
* connector_rate_windows: calls started per connector per minute.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_circuits",
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "closed",
                "open",
                "half_open",
                name="circuit_state",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="closed",
            nullable=False,
        ),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_connector_circuits_connector_same_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("connector_id", name=op.f("pk_connector_circuits")),
    )
    op.create_table(
        "connector_rate_windows",
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("calls", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_connector_rate_windows_connector_same_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "connector_id", "window_start", name=op.f("pk_connector_rate_windows")
        ),
    )


def downgrade() -> None:
    op.drop_table("connector_rate_windows")
    op.drop_table("connector_circuits")
