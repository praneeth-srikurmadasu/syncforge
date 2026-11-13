"""Widen the employee name index to the directory's full sort key.

`ix_employees_organization_id_last_name` (organization_id, last_name) is replaced by
(organization_id, last_name, first_name, id): the order of the employee list (v1
`sort=last_name`, v2 keyset pagination). Measured (docs/performance.md): with the old index
PostgreSQL still sorted every page, and the last page by OFFSET fell back to a sequential
scan.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_employees_organization_id_name_order",
        "employees",
        ["organization_id", "last_name", "first_name", "id"],
    )
    op.drop_index("ix_employees_organization_id_last_name", table_name="employees")


def downgrade() -> None:
    op.create_index(
        "ix_employees_organization_id_last_name", "employees", ["organization_id", "last_name"]
    )
    op.drop_index("ix_employees_organization_id_name_order", table_name="employees")
