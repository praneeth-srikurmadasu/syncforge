"""Add employees.version for optimistic concurrency (ETag / If-Match).

Existing rows start at version 1.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "employees", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_check_constraint(op.f("ck_employees_version_positive"), "employees", "version >= 1")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_employees_version_positive"), "employees", type_="check")
    op.drop_column("employees", "version")
