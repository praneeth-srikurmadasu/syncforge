"""Add auth_rate_windows: fixed-window counters for sign-in and registration limits.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_rate_windows",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hits", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("hits >= 0", name=op.f("ck_auth_rate_windows_hits_non_negative")),
        sa.PrimaryKeyConstraint("key", "window_start", name=op.f("pk_auth_rate_windows")),
    )
    # The cleanup deletes by age across all keys.
    op.create_index(
        op.f("ix_auth_rate_windows_window_start"), "auth_rate_windows", ["window_start"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_rate_windows_window_start"), table_name="auth_rate_windows")
    op.drop_table("auth_rate_windows")
