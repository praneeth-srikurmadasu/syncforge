"""Department and employee use cases.

Authorization runs before these methods (the `require_org_permission` dependency).
This module enforces the business rules:

* references (department, manager) must exist in the same organization;
* a manager must not be terminated, and the reporting line must not form a cycle;
* employee numbers and emails are unique per organization;
* termination is final: a terminated employee cannot be edited, and their direct
  reports move to the terminated employee's own manager;
* only terminated employees can be archived (soft-deleted).

Each change is classified into lifecycle events (app/events/lifecycle.py), which are
written to the transactional outbox (app/events/outbox.py) in the same database
transaction as the change itself: the employee row, its events and their outbox rows
commit together or not at all.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.audit import field_changes
from app.core.errors import (
    ConflictError,
    NotFoundError,
    PreconditionFailedError,
    UnprocessableError,
)
from app.events.lifecycle import (
    LifecycleEvent,
    classify_update,
    created_event,
    diff,
    snapshot,
)
from app.events.outbox import record_events
from app.models import Department, Employee, EmploymentStatus, IntegrationEvent, Organization
from app.repositories.employees import DepartmentRepository, EmployeeRepository
from app.schemas.employees import EmployeeCreate

logger = logging.getLogger("syncforge.employees")

# Database constraint name -> (error code, message). Used when a concurrent request
# wins the race between our pre-check and the INSERT/UPDATE.
_UNIQUE_VIOLATIONS = {
    "uq_employees_organization_id_employee_number": (
        "employee_number_taken",
        "This employee number is already in use.",
    ),
    "uq_employees_organization_id_email": ("email_taken", "This email is already in use."),
    "uq_departments_organization_id_lower_name": (
        "department_name_taken",
        "A department with this name already exists.",
    ),
}


def _conflict(constraint: str) -> ConflictError:
    code, message = _UNIQUE_VIOLATIONS[constraint]
    return ConflictError(message, code=code)


def _today() -> date:
    return datetime.now(UTC).date()


def _translate_integrity_error(exc: IntegrityError) -> ConflictError | UnprocessableError:
    text = str(exc.orig)
    for constraint in _UNIQUE_VIOLATIONS:
        if constraint in text:
            return _conflict(constraint)
    if "fk_employees_department_same_organization" in text:
        return UnprocessableError("Department not found.", code="department_not_found")
    if "fk_employees_manager_same_organization" in text:
        return UnprocessableError("Manager not found.", code="manager_not_found")
    raise exc  # not a rule we know how to explain: let it surface as a 500


class DepartmentService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.departments = DepartmentRepository(session)

    def get(self, organization: Organization, department_id: uuid.UUID) -> Department:
        department = self.departments.get(organization.id, department_id)
        if department is None:
            raise NotFoundError("Department not found.", code="department_not_found")
        return department

    def create(self, organization: Organization, *, name: str) -> Department:
        if self.departments.name_taken(organization.id, name):
            raise _conflict("uq_departments_organization_id_lower_name")
        department = Department(organization_id=organization.id, name=name)

        def add() -> None:
            self.departments.add(department)
            self.session.flush()
            self._audit(organization, "department.created", department.id, {"name": name})

        self._commit(add)
        logger.info(
            "department created",
            extra={"organization_id": str(organization.id), "department_id": str(department.id)},
        )
        return department

    def rename(
        self, organization: Organization, department_id: uuid.UUID, *, name: str
    ) -> Department:
        department = self.get(organization, department_id)
        if self.departments.name_taken(organization.id, name, exclude_id=department.id):
            raise _conflict("uq_departments_organization_id_lower_name")
        previous = department.name
        department.name = name
        self._audit(
            organization, "department.renamed", department.id, {"from": previous, "to": name}
        )
        self._commit(self.session.flush)
        return department

    def delete(self, organization: Organization, department_id: uuid.UUID) -> None:
        department = self.get(organization, department_id)
        in_use = self.departments.employee_count(organization.id, department.id)
        if in_use:
            raise ConflictError(
                "Department still has employees. Move them to another department first.",
                code="department_in_use",
                details={"employee_count": in_use},
            )
        try:
            self._audit(
                organization, "department.deleted", department.id, {"name": department.name}
            )
            self.departments.delete(department)
            self.session.commit()
        except IntegrityError as exc:  # an employee was assigned concurrently
            self.session.rollback()
            raise ConflictError(
                "Department still has employees.", code="department_in_use"
            ) from exc
        logger.info(
            "department deleted",
            extra={"organization_id": str(organization.id), "department_id": str(department_id)},
        )

    def _audit(
        self, organization: Organization, action: str, department_id: uuid.UUID, details: dict
    ) -> None:
        audit.record(
            self.session,
            organization_id=organization.id,
            action=action,
            resource_type="department",
            resource_id=department_id,
            details=details,
        )

    def employee_count(self, organization: Organization, department: Department) -> int:
        return self.departments.employee_count(organization.id, department.id)

    def _commit(self, operation: Any) -> None:
        try:
            operation()
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise _translate_integrity_error(exc) from exc


class EmployeeService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.employees = EmployeeRepository(session)
        self.departments = DepartmentRepository(session)
        # Events produced by the last successful operation, and their stored records.
        self.emitted_events: list[LifecycleEvent] = []
        self.recorded_events: list[IntegrationEvent] = []

    # ---- reads -----------------------------------------------------------------------

    def get(self, organization: Organization, employee_id: uuid.UUID) -> Employee:
        employee = self.employees.get(organization.id, employee_id)
        if employee is None:
            raise NotFoundError("Employee not found.", code="employee_not_found")
        return employee

    # ---- create ----------------------------------------------------------------------

    def create(
        self,
        organization: Organization,
        payload: EmployeeCreate,
        *,
        before_commit: Callable[[Employee], None] | None = None,
    ) -> Employee:
        """Create an employee and record `employee.created` (transactional outbox).

        `before_commit` runs inside the transaction, after the employee is flushed: the
        API uses it to store the idempotency record atomically with the employee."""
        org_id = organization.id
        self._check_unique(org_id, payload.employee_number, payload.email)
        self._check_department(org_id, payload.department_id)
        self._check_manager(org_id, payload.manager_id, employee_id=None)

        employee = Employee(organization_id=org_id, **payload.model_dump())
        try:
            self.employees.add(employee)
            events = [created_event(employee)]
            records = record_events(self.session, events)
            self._audit("employee.created", employee, field_changes(events[0].changes))
            if before_commit is not None:
                before_commit(employee)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise _translate_integrity_error(exc) from exc

        self.session.refresh(employee)
        self._committed(events, records)
        return employee

    # ---- update ----------------------------------------------------------------------

    def update(
        self,
        organization: Organization,
        employee_id: uuid.UUID,
        changes: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> Employee:
        """Apply `changes`. With `expected_version` (the client's If-Match), refuse with
        412 if the employee changed since the client read it (optimistic concurrency)."""
        org_id = organization.id
        if "manager_id" in changes:
            # Serialize reporting-line changes in this organization, so two concurrent
            # requests (A reports to B, B reports to A) cannot together form a cycle.
            self.employees.lock_hierarchy(org_id)
        employee = self._get_for_update(org_id, employee_id, expected_version)
        if employee.employment_status is EmploymentStatus.TERMINATED:
            raise ConflictError(
                "A terminated employee cannot be modified.", code="employee_terminated"
            )

        self._check_unique(
            org_id, changes.get("employee_number"), changes.get("email"), exclude_id=employee.id
        )
        if changes.get("department_id") is not None:
            self._check_department(org_id, changes["department_id"])
        if changes.get("manager_id") is not None:
            self._check_manager(org_id, changes["manager_id"], employee_id=employee.id)

        before = snapshot(employee)
        for name, value in changes.items():
            setattr(employee, name, value)
        events = classify_update(org_id, employee.id, diff(before, snapshot(employee)))
        if not events:
            # Nothing changed, so no UPDATE is issued; commit just releases the locks.
            self.session.commit()
            self._committed([], [])
            return employee

        try:
            records = record_events(self.session, events)
            self._audit(
                "employee.updated",
                employee,
                {
                    **field_changes(diff(before, snapshot(employee))),
                    "events": [e.type.value for e in events],
                },
            )
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise _translate_integrity_error(exc) from exc

        self.session.refresh(employee)
        self._committed(events, records)
        return employee

    # ---- terminate -------------------------------------------------------------------

    def terminate(
        self,
        organization: Organization,
        employee_id: uuid.UUID,
        *,
        termination_date: date | None,
        expected_version: int | None = None,
    ) -> Employee:
        org_id = organization.id
        self.employees.lock_hierarchy(org_id)  # direct reports are about to move
        employee = self._get_for_update(org_id, employee_id, expected_version)
        if employee.employment_status is EmploymentStatus.TERMINATED:
            raise ConflictError("Employee is already terminated.", code="employee_terminated")

        last_day = termination_date or _today()
        if last_day < employee.joining_date:
            raise UnprocessableError(
                "Termination date cannot be before the joining date.",
                code="termination_before_joining",
            )

        before = snapshot(employee)
        employee.employment_status = EmploymentStatus.TERMINATED
        employee.termination_date = last_day
        events = classify_update(org_id, employee.id, diff(before, snapshot(employee)))

        # Direct reports move up one level, to the terminated employee's manager
        # (or to no manager if the terminated employee had none).
        moved = 0
        for report in self.employees.direct_reports(org_id, employee.id, for_update=True):
            moved += 1
            report_before = snapshot(report)
            report.manager_id = employee.manager_id
            events += classify_update(org_id, report.id, diff(report_before, snapshot(report)))

        records = record_events(self.session, events)
        self._audit(
            "employee.terminated",
            employee,
            {"termination_date": last_day, "direct_reports_moved": moved},
        )
        self.session.commit()
        self.session.refresh(employee)
        self._committed(events, records)
        return employee

    # ---- archive ---------------------------------------------------------------------

    def archive(
        self,
        organization: Organization,
        employee_id: uuid.UUID,
        *,
        expected_version: int | None = None,
    ) -> None:
        """Soft delete. Idempotent: archiving an archived employee changes nothing."""
        employee = self._get_for_update(organization.id, employee_id, expected_version)
        if employee.employment_status is not EmploymentStatus.TERMINATED:
            raise ConflictError(
                "Only terminated employees can be archived. Terminate the employee first.",
                code="employee_not_terminated",
            )
        if employee.archived_at is None:
            employee.archived_at = datetime.now(UTC)
            self._audit("employee.archived", employee, {})
            self.session.commit()
            logger.info(
                "employee archived",
                extra={"organization_id": str(organization.id), "employee_id": str(employee_id)},
            )

    # ---- rules -----------------------------------------------------------------------

    def _audit(self, action: str, employee: Employee, details: dict[str, Any]) -> None:
        audit.record(
            self.session,
            organization_id=employee.organization_id,
            action=action,
            resource_type="employee",
            resource_id=employee.id,
            details=details,
        )

    def _get_for_update(
        self,
        organization_id: uuid.UUID,
        employee_id: uuid.UUID,
        expected_version: int | None = None,
    ) -> Employee:
        """Lock the row; then compare versions. The lock makes the check and the write
        one atomic step: no other transaction can change the row in between."""
        employee = self.employees.get(organization_id, employee_id, for_update=True)
        if employee is None:
            raise NotFoundError("Employee not found.", code="employee_not_found")
        if expected_version is not None and employee.version != expected_version:
            current = employee.version
            self.session.rollback()  # release the row lock
            raise PreconditionFailedError(
                "This employee was changed by someone else since you loaded it. Reload, "
                "re-apply your change and save again.",
                code="version_conflict",
                details={"expected_version": expected_version, "current_version": current},
            )
        return employee

    def _check_unique(
        self,
        organization_id: uuid.UUID,
        employee_number: str | None,
        email: str | None,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        if employee_number is not None and self.employees.employee_number_taken(
            organization_id, employee_number, exclude_id=exclude_id
        ):
            raise _conflict("uq_employees_organization_id_employee_number")
        if email is not None and self.employees.email_taken(
            organization_id, email, exclude_id=exclude_id
        ):
            raise _conflict("uq_employees_organization_id_email")

    def _check_department(
        self, organization_id: uuid.UUID, department_id: uuid.UUID | None
    ) -> None:
        if (
            department_id is not None
            and self.departments.get(organization_id, department_id) is None
        ):
            # Same response whether the ID is unknown or belongs to another organization.
            raise UnprocessableError("Department not found.", code="department_not_found")

    def _check_manager(
        self,
        organization_id: uuid.UUID,
        manager_id: uuid.UUID | None,
        *,
        employee_id: uuid.UUID | None,
    ) -> None:
        if manager_id is None:
            return
        if manager_id == employee_id:
            raise UnprocessableError("An employee cannot manage themselves.", code="manager_cycle")
        manager = self.employees.get(organization_id, manager_id)
        if manager is None:
            raise UnprocessableError("Manager not found.", code="manager_not_found")
        if manager.employment_status is EmploymentStatus.TERMINATED:
            raise UnprocessableError(
                "A terminated employee cannot be a manager.", code="manager_terminated"
            )
        if employee_id is not None and employee_id in self.employees.management_chain(
            organization_id, manager_id
        ):
            raise UnprocessableError(
                "This manager reports (directly or indirectly) to the employee; "
                "the reporting line would form a cycle.",
                code="manager_cycle",
            )

    def _committed(self, events: list[LifecycleEvent], records: list[IntegrationEvent]) -> None:
        """Log events once their transaction has committed (never before)."""
        self.emitted_events = events
        self.recorded_events = records
        for event, record in zip(events, records, strict=True):
            # IDs and field names only - never the values, which can be personal data.
            logger.info(
                "employee lifecycle event",
                extra={
                    "event_type": event.type.value,
                    "event_id": str(record.id),
                    "organization_id": str(event.organization_id),
                    "employee_id": str(event.employee_id),
                    "changed_fields": sorted(event.changes),
                },
            )
