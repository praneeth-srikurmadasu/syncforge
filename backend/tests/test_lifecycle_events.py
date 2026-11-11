"""Unit tests for lifecycle event detection (pure functions, no database)."""

import uuid
from datetime import date

from app.events.lifecycle import (
    EmployeeEventType,
    LifecycleEvent,
    classify_update,
    created_event,
    diff,
)
from app.models import Employee, EmploymentStatus

ORG = uuid.uuid4()
EMP = uuid.uuid4()
DEPT_A, DEPT_B = uuid.uuid4(), uuid.uuid4()
BOSS_A, BOSS_B = uuid.uuid4(), uuid.uuid4()


def base_snapshot(**overrides: object) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "employee_number": "E-1001",
        "first_name": "Grace",
        "last_name": "Hopper",
        "email": "grace@acme.example",
        "department_id": DEPT_A,
        "designation": "Engineer",
        "manager_id": BOSS_A,
        "location": "Bengaluru",
        "employment_status": EmploymentStatus.ACTIVE,
        "joining_date": date(2024, 1, 15),
        "termination_date": None,
    }
    snapshot.update(overrides)
    return snapshot


def events_for(**overrides: object) -> list[LifecycleEvent]:
    return classify_update(ORG, EMP, diff(base_snapshot(), base_snapshot(**overrides)))


def types(events: list[LifecycleEvent]) -> list[EmployeeEventType]:
    return [event.type for event in events]


def test_no_change_produces_no_events() -> None:
    assert events_for() == []


def test_department_change() -> None:
    events = events_for(department_id=DEPT_B)

    assert types(events) == [EmployeeEventType.DEPARTMENT_CHANGED]
    assert events[0].changes == {"department_id": (DEPT_A, DEPT_B)}


def test_manager_change() -> None:
    events = events_for(manager_id=BOSS_B)

    assert types(events) == [EmployeeEventType.MANAGER_CHANGED]
    assert events[0].changes == {"manager_id": (BOSS_A, BOSS_B)}


def test_other_fields_produce_a_single_updated_event() -> None:
    events = events_for(designation="Staff Engineer", location="Pune")

    assert types(events) == [EmployeeEventType.UPDATED]
    assert events[0].changes == {
        "designation": ("Engineer", "Staff Engineer"),
        "location": ("Bengaluru", "Pune"),
    }


def test_termination_takes_status_and_date() -> None:
    events = events_for(
        employment_status=EmploymentStatus.TERMINATED, termination_date=date(2026, 3, 31)
    )

    assert types(events) == [EmployeeEventType.TERMINATED]
    assert events[0].changes == {
        "employment_status": (EmploymentStatus.ACTIVE, EmploymentStatus.TERMINATED),
        "termination_date": (None, date(2026, 3, 31)),
    }


def test_leave_is_an_ordinary_update_not_a_termination() -> None:
    events = events_for(employment_status=EmploymentStatus.ON_LEAVE)

    assert types(events) == [EmployeeEventType.UPDATED]


def test_one_change_can_produce_several_events_in_a_stable_order() -> None:
    events = events_for(department_id=DEPT_B, manager_id=BOSS_B, designation="Lead")

    assert types(events) == [
        EmployeeEventType.DEPARTMENT_CHANGED,
        EmployeeEventType.MANAGER_CHANGED,
        EmployeeEventType.UPDATED,
    ]
    # Each field is reported by exactly one event.
    assert events[2].changes == {"designation": ("Engineer", "Lead")}


def test_payload_is_json_serializable() -> None:
    event = events_for(
        department_id=DEPT_B,
    )[0]

    payload = event.payload()

    assert payload == {
        "type": "employee.department_changed",
        "organization_id": str(ORG),
        "employee_id": str(EMP),
        "changes": {"department_id": {"old": str(DEPT_A), "new": str(DEPT_B)}},
    }


def test_payload_serializes_dates_and_enums() -> None:
    event = events_for(
        employment_status=EmploymentStatus.TERMINATED, termination_date=date(2026, 3, 31)
    )[0]

    assert event.payload()["changes"] == {
        "employment_status": {"old": "active", "new": "terminated"},
        "termination_date": {"old": None, "new": "2026-03-31"},
    }


def test_created_event_lists_initial_non_empty_values() -> None:
    employee = Employee(
        id=EMP,
        organization_id=ORG,
        employee_number="E-1001",
        first_name="Grace",
        last_name="Hopper",
        email="grace@acme.example",
        department_id=DEPT_A,
        manager_id=None,
        designation=None,
        location="Bengaluru",
        employment_status=EmploymentStatus.ACTIVE,
        joining_date=date(2024, 1, 15),
        termination_date=None,
    )

    event = created_event(employee)

    assert event.type is EmployeeEventType.CREATED
    assert event.employee_id == EMP
    assert set(event.changes) == {
        "employee_number",
        "first_name",
        "last_name",
        "email",
        "department_id",
        "location",
        "employment_status",
        "joining_date",
    }
    assert all(old is None for old, _ in event.changes.values())
