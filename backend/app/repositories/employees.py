"""Department and employee data access.

Every query takes an organization_id and filters on it. There is deliberately no
"get employee by id" without an organization: tenant scoping is part of the API of
this module, not something a caller can forget.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, func, literal, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Department, Employee, EmploymentStatus


class EmployeeSort(enum.StrEnum):
    """Allowed `sort` values for the employee list. A leading "-" means descending."""

    LAST_NAME = "last_name"
    LAST_NAME_DESC = "-last_name"
    JOINING_DATE = "joining_date"
    JOINING_DATE_DESC = "-joining_date"
    EMPLOYEE_NUMBER = "employee_number"
    CREATED_AT_DESC = "-created_at"


_SORT_COLUMNS = {
    EmployeeSort.LAST_NAME: (Employee.last_name.asc(), Employee.first_name.asc()),
    EmployeeSort.LAST_NAME_DESC: (Employee.last_name.desc(), Employee.first_name.desc()),
    EmployeeSort.JOINING_DATE: (Employee.joining_date.asc(),),
    EmployeeSort.JOINING_DATE_DESC: (Employee.joining_date.desc(),),
    EmployeeSort.EMPLOYEE_NUMBER: (Employee.employee_number.asc(),),
    EmployeeSort.CREATED_AT_DESC: (Employee.created_at.desc(),),
}


def escape_like(term: str) -> str:
    """Escape LIKE wildcards so a search for '50%' matches the text '50%' literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class EmployeeFilters:
    search: str | None = None
    department_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    employment_status: EmploymentStatus | None = None
    location: str | None = None
    joined_from: date | None = None
    joined_to: date | None = None
    include_archived: bool = False


class DepartmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, organization_id: uuid.UUID, department_id: uuid.UUID) -> Department | None:
        return self.session.scalar(
            select(Department).where(
                Department.organization_id == organization_id, Department.id == department_id
            )
        )

    def name_taken(
        self, organization_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        query = select(Department.id).where(
            Department.organization_id == organization_id,
            func.lower(Department.name) == name.lower(),
        )
        if exclude_id is not None:
            query = query.where(Department.id != exclude_id)
        return self.session.scalar(query) is not None

    def add(self, department: Department) -> Department:
        self.session.add(department)
        self.session.flush()
        return department

    def delete(self, department: Department) -> None:
        self.session.delete(department)
        self.session.flush()

    def employee_count(self, organization_id: uuid.UUID, department_id: uuid.UUID) -> int:
        return (
            self.session.scalar(
                select(func.count()).where(
                    Employee.organization_id == organization_id,
                    Employee.department_id == department_id,
                )
            )
            or 0
        )

    def list_with_counts(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[tuple[Department, int]], int]:
        total = (
            self.session.scalar(
                select(func.count())
                .select_from(Department)
                .where(Department.organization_id == organization_id)
            )
            or 0
        )
        counts = (
            select(Employee.department_id, func.count().label("employee_count"))
            .where(Employee.organization_id == organization_id)
            .group_by(Employee.department_id)
            .subquery()
        )
        rows = self.session.execute(
            select(Department, func.coalesce(counts.c.employee_count, 0))
            .outerjoin(counts, counts.c.department_id == Department.id)
            .where(Department.organization_id == organization_id)
            .order_by(func.lower(Department.name), Department.id)
            .limit(limit)
            .offset(offset)
        )
        return [(department, count) for department, count in rows], total


class EmployeeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _with_refs(self, query: Select[tuple[Employee]]) -> Select[tuple[Employee]]:
        # Load department and manager in batched queries, avoiding N+1 on list pages.
        return query.options(selectinload(Employee.department), selectinload(Employee.manager))

    def get(
        self, organization_id: uuid.UUID, employee_id: uuid.UUID, *, for_update: bool = False
    ) -> Employee | None:
        query = select(Employee).where(
            Employee.organization_id == organization_id, Employee.id == employee_id
        )
        if for_update:
            # Row lock: serializes concurrent changes to the same employee
            # (e.g. two simultaneous terminations).
            query = query.with_for_update()
        return self.session.scalar(self._with_refs(query))

    def add(self, employee: Employee) -> Employee:
        self.session.add(employee)
        self.session.flush()
        return employee

    def employee_number_taken(
        self, organization_id: uuid.UUID, number: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        return self._taken(organization_id, Employee.employee_number == number, exclude_id)

    def email_taken(
        self, organization_id: uuid.UUID, email: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        return self._taken(organization_id, Employee.email == email, exclude_id)

    def _taken(
        self, organization_id: uuid.UUID, condition: object, exclude_id: uuid.UUID | None
    ) -> bool:
        query = select(Employee.id).where(Employee.organization_id == organization_id, condition)
        if exclude_id is not None:
            query = query.where(Employee.id != exclude_id)
        return self.session.scalar(query) is not None

    def lock_hierarchy(self, organization_id: uuid.UUID) -> None:
        """Take a transaction-scoped advisory lock for this organization's reporting lines.

        Row locks alone cannot stop two requests from creating a cycle together
        (A -> B and B -> A each lock a different row), so changes to manager
        relationships in one organization take this lock and run one at a time.
        It is released automatically at commit or rollback.
        """
        key = int.from_bytes(organization_id.bytes[:8], "big", signed=True)
        self.session.execute(select(func.pg_advisory_xact_lock(key)))

    def direct_reports(
        self, organization_id: uuid.UUID, manager_id: uuid.UUID, *, for_update: bool = False
    ) -> list[Employee]:
        query = (
            select(Employee)
            .where(Employee.organization_id == organization_id, Employee.manager_id == manager_id)
            .order_by(Employee.id)
        )
        if for_update:
            query = query.with_for_update()
        return list(self.session.scalars(query))

    def management_chain(
        self, organization_id: uuid.UUID, employee_id: uuid.UUID
    ) -> set[uuid.UUID]:
        """IDs of `employee_id` and everyone above it (its manager, their manager, ...).

        One recursive query instead of one query per level. UNION (not UNION ALL)
        stops the recursion even if the data already contained a cycle.
        """
        chain = (
            select(Employee.id, Employee.manager_id)
            .where(Employee.organization_id == organization_id, Employee.id == employee_id)
            .cte("chain", recursive=True)
        )
        chain = chain.union(
            select(Employee.id, Employee.manager_id).where(
                Employee.organization_id == organization_id, Employee.id == chain.c.manager_id
            )
        )
        return set(self.session.scalars(select(chain.c.id)))

    def list(
        self,
        organization_id: uuid.UUID,
        filters: EmployeeFilters,
        *,
        sort: EmployeeSort,
        limit: int,
        offset: int,
    ) -> tuple[list[Employee], int]:
        conditions = [Employee.organization_id == organization_id]
        if not filters.include_archived:
            conditions.append(Employee.archived_at.is_(None))
        if filters.search:
            pattern = f"%{escape_like(filters.search)}%"
            full_name = Employee.first_name + literal(" ") + Employee.last_name
            conditions.append(
                or_(
                    full_name.ilike(pattern, escape="\\"),
                    Employee.email.ilike(pattern, escape="\\"),
                    Employee.employee_number.ilike(pattern, escape="\\"),
                )
            )
        if filters.department_id is not None:
            conditions.append(Employee.department_id == filters.department_id)
        if filters.manager_id is not None:
            conditions.append(Employee.manager_id == filters.manager_id)
        if filters.employment_status is not None:
            conditions.append(Employee.employment_status == filters.employment_status)
        if filters.location:
            conditions.append(func.lower(Employee.location) == filters.location.lower())
        if filters.joined_from is not None:
            conditions.append(Employee.joining_date >= filters.joined_from)
        if filters.joined_to is not None:
            conditions.append(Employee.joining_date <= filters.joined_to)

        total = self.session.scalar(select(func.count()).select_from(Employee).where(*conditions))
        items = self.session.scalars(
            self._with_refs(
                select(Employee)
                .where(*conditions)
                # Employee.id last: a stable order, so pages never overlap or skip rows.
                .order_by(*_SORT_COLUMNS[sort], Employee.id)
                .limit(limit)
                .offset(offset)
            )
        )
        return list(items), total or 0
