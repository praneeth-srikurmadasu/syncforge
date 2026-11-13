"""Add component_heartbeats: liveness of workers and the outbox relay.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "component_heartbeats",
        sa.Column("component", sa.String(length=20), nullable=False),
        sa.Column("instance", sa.String(length=200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("component", "instance", name=op.f("pk_component_heartbeats")),
    )


def downgrade() -> None:
    op.drop_table("component_heartbeats")
