"""Departments and employees - the workforce data SyncForge synchronizes.

Tenant integrity is enforced by the database, not only by application code:
an employee's department and manager are referenced through *composite* foreign
keys on (organization_id, id). A row can therefore only point at a department or
manager in the same organization - a cross-tenant reference is impossible even if
application code has a bug.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EmploymentStatus(enum.StrEnum):
    """Lifecycle: active <-> on_leave -> terminated. Termination is final."""

    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class Department(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (
        # Target of the composite foreign key from employees.
        UniqueConstraint("organization_id", "id"),
        # Department names are unique per organization, ignoring case.
        Index(
            "uq_departments_organization_id_lower_name",
            "organization_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    def __repr__(self) -> str:
        return f"<Department {self.id}>"


class Employee(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("organization_id", "employee_number"),
        UniqueConstraint("organization_id", "email"),
        # Target of the self-referencing composite foreign key (manager).
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "department_id"],
            ["departments.organization_id", "departments.id"],
            name="fk_employees_department_same_organization",
        ),
        ForeignKeyConstraint(
            ["organization_id", "manager_id"],
            ["employees.organization_id", "employees.id"],
            name="fk_employees_manager_same_organization",
        ),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("manager_id IS NULL OR manager_id <> id", name="not_own_manager"),
        CheckConstraint(
            "(employment_status = 'terminated') = (termination_date IS NOT NULL)",
            name="termination_date_matches_status",
        ),
        CheckConstraint(
            "termination_date IS NULL OR termination_date >= joining_date",
            name="termination_not_before_joining",
        ),
        # Indexes for the list/search/filter queries (always scoped by organization).
        # The directory's default order (v1 sort=last_name, v2 keyset): the full sort key,
        # ending in the unique ID, so pages are read in index order without a sort step
        # (chosen from measurements, docs/performance.md).
        Index(
            "ix_employees_organization_id_name_order",
            "organization_id",
            "last_name",
            "first_name",
            "id",
        ),
        Index("ix_employees_organization_id_status", "organization_id", "employment_status"),
        Index("ix_employees_organization_id_department_id", "organization_id", "department_id"),
        Index("ix_employees_organization_id_manager_id", "organization_id", "manager_id"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Business identifier from the HR system ("Employee ID"), unique per organization.
    employee_number: Mapped[str] = mapped_column(String(50), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column()
    designation: Mapped[str | None] = mapped_column(String(150))
    manager_id: Mapped[uuid.UUID | None] = mapped_column()
    location: Mapped[str | None] = mapped_column(String(150))
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        Enum(
            EmploymentStatus,
            name="employment_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        nullable=False,
        server_default=EmploymentStatus.ACTIVE.value,
    )
    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None] = mapped_column(Date)
    # Soft delete: archived employees are hidden from default lists but kept for history.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Optimistic concurrency: incremented by SQLAlchemy on every UPDATE of the row
    # (`version_id_col`, so the UPDATE also carries `WHERE version = <read version>`).
    # Exposed as the ETag; clients send it back in If-Match, and a stale edit is refused
    # with 412 instead of silently overwriting someone else's change (docs/data-integrity.md).
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    __mapper_args__ = {"version_id_col": version}

    department: Mapped[Department | None] = relationship(
        foreign_keys=[organization_id, department_id],
        primaryjoin="and_(Employee.organization_id == Department.organization_id, "
        "Employee.department_id == Department.id)",
        viewonly=True,
    )
    manager: Mapped["Employee | None"] = relationship(
        foreign_keys=[organization_id, manager_id],
        primaryjoin="and_(Employee.organization_id == remote(Employee.organization_id), "
        "Employee.manager_id == remote(Employee.id))",
        viewonly=True,
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<Employee {self.id}>"  # no name or email: keeps PII out of logs
