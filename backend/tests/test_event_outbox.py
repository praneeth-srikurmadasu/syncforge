"""Transactional outbox: every employee change commits together with its integration
events and outbox rows - or none of them commit."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.events import outbox
from app.models import (
    Employee,
    IntegrationEvent,
    IntegrationEventStatus,
    Organization,
    OrganizationRole,
    OutboxEvent,
)
from app.schemas.employees import EmployeeCreate
from app.services.employees import EmployeeService
from tests.factories import (
    add_member,
    auth_headers,
    create_department,
    create_employee,
    create_organization,
    create_user,
)


def admin(session: Session, org: Organization) -> dict[str, str]:
    user = create_user(session)
    add_member(session, user, org, OrganizationRole.ORG_ADMIN)
    return auth_headers(user)


def events_for(session: Session, org: Organization) -> list[IntegrationEvent]:
    return list(
        session.scalars(
            select(IntegrationEvent)
            .where(IntegrationEvent.organization_id == org.id)
            .order_by(IntegrationEvent.created_at, IntegrationEvent.event_type)
        )
    )


def outbox_rows(session: Session, events: list[IntegrationEvent]) -> list[OutboxEvent]:
    ids = [e.id for e in events]
    return list(session.scalars(select(OutboxEvent).where(OutboxEvent.event_id.in_(ids))))


def new_employee(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "employee_number": f"E-{uuid.uuid4().hex[:6]}",
        "first_name": "Grace",
        "last_name": "Hopper",
        "email": f"grace.{uuid.uuid4().hex[:6]}@acme.example",
        "joining_date": "2024-01-15",
    }
    body.update(overrides)
    return body


def test_create_records_one_pending_event_and_one_unpublished_outbox_row(
    client: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)

    response = client.post(
        f"/api/v1/organizations/{org.id}/employees",
        json=new_employee(),
        headers={**admin(db_session, org), "X-Request-ID": "req-outbox-1"},
    )

    assert response.status_code == 201
    [event] = events_for(db_session, org)
    assert event.event_type == "employee.created"
    assert str(event.employee_id) == response.json()["id"]
    assert event.status is IntegrationEventStatus.PENDING
    assert event.attempts == 0 and event.locked_until is None
    assert event.correlation_id == "req-outbox-1"  # links the request log to the event
    assert event.payload["type"] == "employee.created"
    assert event.payload["changes"]["first_name"] == {"old": None, "new": "Grace"}

    [row] = outbox_rows(db_session, [event])
    assert row.published_at is None and row.publish_attempts == 0


def test_one_update_records_one_event_per_lifecycle_event(
    client: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)
    sales = create_department(db_session, org, "Sales")

    response = client.patch(
        f"/api/v1/organizations/{org.id}/employees/{employee.id}",
        json={"department_id": str(sales.id), "location": "Pune"},
        headers=admin(db_session, org),
    )

    assert response.status_code == 200
    events = events_for(db_session, org)
    assert sorted(e.event_type for e in events) == [
        "employee.department_changed",
        "employee.updated",
    ]
    assert len(outbox_rows(db_session, events)) == 2
    # Both events came from the same request.
    assert len({e.correlation_id for e in events}) == 1


def test_termination_records_events_for_the_employee_and_moved_reports(
    client: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    boss = create_employee(db_session, org, first_name="Ada")
    manager = create_employee(db_session, org, first_name="Alan", manager=boss)
    report = create_employee(db_session, org, first_name="Linus", manager=manager)

    response = client.post(
        f"/api/v1/organizations/{org.id}/employees/{manager.id}/terminate",
        json={},
        headers=admin(db_session, org),
    )

    assert response.status_code == 200
    recorded = {(e.event_type, e.employee_id) for e in events_for(db_session, org)}
    assert recorded == {
        ("employee.terminated", manager.id),
        ("employee.manager_changed", report.id),
    }


def test_rejected_and_no_op_changes_record_nothing(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    existing = create_employee(db_session, org)
    headers = admin(db_session, org)

    duplicate = client.post(
        f"/api/v1/organizations/{org.id}/employees",
        json=new_employee(email=existing.email),
        headers=headers,
    )
    no_op = client.patch(
        f"/api/v1/organizations/{org.id}/employees/{existing.id}",
        json={"location": existing.location},
        headers=headers,
    )

    assert duplicate.status_code == 409 and no_op.status_code == 200
    assert events_for(db_session, org) == []


def test_employee_change_and_its_events_share_one_transaction(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If writing the outbox fails, the employee change must be rolled back too."""
    org = create_organization(db_session)
    real_record = outbox.record_events

    def broken_record(session: Session, events: list) -> list[IntegrationEvent]:
        records = real_record(session, events)
        # An outbox row pointing at a non-existent event: the commit will fail.
        session.add(OutboxEvent(event_id=uuid.uuid4()))
        return records

    monkeypatch.setattr("app.services.employees.record_events", broken_record)
    payload = EmployeeCreate.model_validate(new_employee(employee_number="E-ATOMIC"))

    with pytest.raises(IntegrityError):
        EmployeeService(db_session).create(org, payload)

    assert db_session.scalar(select(func.count()).select_from(Employee)) == 0
    assert db_session.scalar(select(func.count()).select_from(IntegrationEvent)) == 0
    assert db_session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


def test_lifecycle_log_line_carries_the_event_id(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="syncforge.employees")
    org = create_organization(db_session)
    service = EmployeeService(db_session)

    service.create(org, EmployeeCreate.model_validate(new_employee()))

    [record] = [r for r in caplog.records if r.getMessage() == "employee lifecycle event"]
    assert record.event_id == str(service.recorded_events[0].id)  # type: ignore[attr-defined]
    assert record.event_type == "employee.created"  # type: ignore[attr-defined]


def test_events_of_one_organization_cannot_reference_another_organizations_employee(
    db_session: Session,
) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    globex_employee = create_employee(db_session, globex)

    db_session.add(
        IntegrationEvent(
            organization_id=acme.id,
            event_type="employee.updated",
            employee_id=globex_employee.id,
            payload={},
        )
    )
    with pytest.raises(IntegrityError, match="fk_integration_events_employee_same_organization"):
        db_session.flush()


def test_event_status_is_constrained(db_session: Session) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)
    event = IntegrationEvent(
        organization_id=org.id, event_type="employee.updated", employee_id=employee.id, payload={}
    )
    db_session.add(event)
    db_session.flush()

    with pytest.raises(IntegrityError, match="integration_event_status"):
        db_session.execute(
            text("UPDATE integration_events SET status = 'exploded' WHERE id = :id"),
            {"id": event.id},
        )
