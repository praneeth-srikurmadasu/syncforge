"""Employee lifecycle event detection.

Events are derived by comparing an employee's tracked fields before and after a
change. Detection is a pure function (no database, no I/O), so the rules are easy
to unit test and reuse.

Rules for an update (several events can come from one change):
  employment_status -> terminated   => employee.terminated
  department_id changed             => employee.department_changed
  manager_id changed                => employee.manager_changed
  any other tracked field changed   => employee.updated (lists only those fields)
A change that alters nothing produces no events.

Detected events are written to the transactional outbox (app/events/outbox.py) in the
same database transaction as the employee change.
"""

import enum
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.models import Employee, EmploymentStatus


class EmployeeEventType(enum.StrEnum):
    CREATED = "employee.created"
    UPDATED = "employee.updated"
    DEPARTMENT_CHANGED = "employee.department_changed"
    MANAGER_CHANGED = "employee.manager_changed"
    TERMINATED = "employee.terminated"


# Fields whose changes are significant for downstream systems.
TRACKED_FIELDS: tuple[str, ...] = (
    "employee_number",
    "first_name",
    "last_name",
    "email",
    "department_id",
    "designation",
    "manager_id",
    "location",
    "employment_status",
    "joining_date",
    "termination_date",
)

Snapshot = dict[str, Any]
Changes = dict[str, tuple[Any, Any]]  # field -> (old value, new value)


@dataclass(frozen=True)
class LifecycleEvent:
    type: EmployeeEventType
    organization_id: uuid.UUID
    employee_id: uuid.UUID
    changes: Changes = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        """JSON-serializable representation (UUIDs and dates as strings)."""
        return {
            "type": self.type.value,
            "organization_id": str(self.organization_id),
            "employee_id": str(self.employee_id),
            "changes": {
                name: {"old": _jsonable(old), "new": _jsonable(new)}
                for name, (old, new) in self.changes.items()
            },
        }


def snapshot(employee: Employee) -> Snapshot:
    return {name: getattr(employee, name) for name in TRACKED_FIELDS}


def diff(before: Snapshot, after: Snapshot) -> Changes:
    return {
        name: (before.get(name), after.get(name))
        for name in TRACKED_FIELDS
        if before.get(name) != after.get(name)
    }


def created_event(employee: Employee) -> LifecycleEvent:
    after = snapshot(employee)
    return LifecycleEvent(
        type=EmployeeEventType.CREATED,
        organization_id=employee.organization_id,
        employee_id=employee.id,
        changes={name: (None, value) for name, value in after.items() if value is not None},
    )


def classify_update(
    organization_id: uuid.UUID, employee_id: uuid.UUID, changes: Changes
) -> list[LifecycleEvent]:
    remaining = dict(changes)
    events: list[LifecycleEvent] = []

    def emit(event_type: EmployeeEventType, *fields: str) -> None:
        taken = {name: remaining.pop(name) for name in fields if name in remaining}
        events.append(LifecycleEvent(event_type, organization_id, employee_id, taken))

    status_change = changes.get("employment_status")
    if status_change and status_change[1] == EmploymentStatus.TERMINATED:
        emit(EmployeeEventType.TERMINATED, "employment_status", "termination_date")
    if "department_id" in changes:
        emit(EmployeeEventType.DEPARTMENT_CHANGED, "department_id")
    if "manager_id" in changes:
        emit(EmployeeEventType.MANAGER_CHANGED, "manager_id")
    if remaining:
        events.append(
            LifecycleEvent(EmployeeEventType.UPDATED, organization_id, employee_id, remaining)
        )
    return events


def _jsonable(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value
