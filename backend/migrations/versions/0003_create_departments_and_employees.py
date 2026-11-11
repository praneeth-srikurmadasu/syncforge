"""Create departments and employees.

Employees reference their department and manager through composite foreign keys on
(organization_id, id), so a cross-organization reference is rejected by the database.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
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
        "departments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_departments_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_departments_organization_id_id")
        ),
    )
    # Case-insensitive unique name per organization ("Engineering" == "engineering").
    op.create_index(
        "uq_departments_organization_id_lower_name",
        "departments",
        ["organization_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("employee_number", sa.String(length=50), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=True),
        sa.Column("designation", sa.String(length=150), nullable=True),
        sa.Column("manager_id", sa.Uuid(), nullable=True),
        sa.Column("location", sa.String(length=150), nullable=True),
        sa.Column(
            "employment_status",
            sa.Enum(
                "active",
                "on_leave",
                "terminated",
                name="employment_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("joining_date", sa.Date(), nullable=False),
        sa.Column("termination_date", sa.Date(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_employees_email_lowercase")),
        sa.CheckConstraint(
            "manager_id IS NULL OR manager_id <> id", name=op.f("ck_employees_not_own_manager")
        ),
        sa.CheckConstraint(
            "(employment_status = 'terminated') = (termination_date IS NOT NULL)",
            name=op.f("ck_employees_termination_date_matches_status"),
        ),
        sa.CheckConstraint(
            "termination_date IS NULL OR termination_date >= joining_date",
            name=op.f("ck_employees_termination_not_before_joining"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_employees_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "department_id"],
            ["departments.organization_id", "departments.id"],
            name="fk_employees_department_same_organization",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "manager_id"],
            ["employees.organization_id", "employees.id"],
            name="fk_employees_manager_same_organization",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employees")),
        sa.UniqueConstraint(
            "organization_id",
            "employee_number",
            name=op.f("uq_employees_organization_id_employee_number"),
        ),
        sa.UniqueConstraint(
            "organization_id", "email", name=op.f("uq_employees_organization_id_email")
        ),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_employees_organization_id_id")),
    )
    op.create_index(
        "ix_employees_organization_id_last_name", "employees", ["organization_id", "last_name"]
    )
    op.create_index(
        "ix_employees_organization_id_status", "employees", ["organization_id", "employment_status"]
    )
    op.create_index(
        "ix_employees_organization_id_department_id",
        "employees",
        ["organization_id", "department_id"],
    )
    op.create_index(
        "ix_employees_organization_id_manager_id", "employees", ["organization_id", "manager_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_employees_organization_id_manager_id", table_name="employees")
    op.drop_index("ix_employees_organization_id_department_id", table_name="employees")
    op.drop_index("ix_employees_organization_id_status", table_name="employees")
    op.drop_index("ix_employees_organization_id_last_name", table_name="employees")
    op.drop_table("employees")
    op.drop_index("uq_departments_organization_id_lower_name", table_name="departments")
    op.drop_table("departments")
