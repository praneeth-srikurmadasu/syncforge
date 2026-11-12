"""API tests for integration events: listing, filters, detail with executions,
no personal data in responses, and tenant isolation."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    IntegrationEventStatus,
    JobStatus,
    Organization,
    OrganizationRole,
    SynchronizationJob,
    Workflow,
    WorkflowExecution,
)
from app.services.employees import EmployeeService
from tests.factories import (
    add_member,
    auth_headers,
    create_connector,
    create_department,
    create_employee,
    create_organization,
    create_user,
)


def url(org: Organization, *parts: object) -> str:
    return "/".join([f"/api/v1/organizations/{org.id}/events", *map(str, parts)])


def viewer(session: Session, org: Organization) -> dict[str, str]:
    user = create_user(session)
    add_member(session, user, org, OrganizationRole.VIEWER)
    return auth_headers(user)


def test_events_are_listed_without_personal_data(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org, first_name="Grace", last_name="Hopper")
    service = EmployeeService(db_session)
    service.update(org, employee.id, {"location": "Pune"})
    service.update(org, employee.id, {"designation": "Staff Engineer"})

    response = client.get(url(org), headers=viewer(db_session, org))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    # Both changes ran inside this test's single transaction, so they share created_at
    # (PostgreSQL now() is the transaction start); compare without relying on order.
    assert sorted(e["changed_fields"] for e in body["items"]) == [["designation"], ["location"]]
    first = body["items"][0]
    assert (first["event_type"], first["status"], first["attempts"]) == (
        "employee.updated",
        "pending",
        0,
    )
    # Values (here: "Pune", "Staff Engineer") are stored for workers, never returned.
    assert "Pune" not in response.text and "Staff Engineer" not in response.text


def test_filters(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    alice, bob = create_employee(db_session, org), create_employee(db_session, org)
    sales = create_department(db_session, org, "Sales")
    service = EmployeeService(db_session)
    service.update(org, alice.id, {"department_id": sales.id})
    service.update(org, bob.id, {"location": "Pune"})
    service.recorded_events[0].status = IntegrationEventStatus.COMPLETED
    db_session.flush()
    headers = viewer(db_session, org)

    def types(**params: str) -> list[str]:
        items = client.get(url(org), params=params, headers=headers).json()["items"]
        return sorted(e["event_type"] for e in items)

    assert types(event_type="employee.department_changed") == ["employee.department_changed"]
    assert types(employee_id=str(bob.id)) == ["employee.updated"]
    assert types(event_status="completed") == ["employee.updated"]
    assert types(event_status="dead_letter") == []
    invalid = client.get(url(org), params={"event_type": "nope"}, headers=headers)
    assert invalid.status_code == 422


def test_event_detail_includes_executions_and_steps(
    client: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)
    service = EmployeeService(db_session)
    service.update(org, employee.id, {"location": "Pune"})
    event = service.recorded_events[0]
    connector = create_connector(db_session, org)
    workflow = Workflow(organization_id=org.id, name="Sync", trigger_event_type="employee.updated")
    db_session.add(workflow)
    db_session.flush()
    execution = WorkflowExecution(
        organization_id=org.id, event_id=event.id, workflow_id=workflow.id, workflow_version=1
    )
    execution.jobs = [
        SynchronizationJob(
            organization_id=org.id,
            position=1,
            connector_id=connector.id,
            operation="update_user",
            employee_id=employee.id,
            status=JobStatus.RUNNING,
        )
    ]
    db_session.add(execution)
    db_session.flush()

    body = client.get(url(org, event.id), headers=viewer(db_session, org)).json()

    assert body["id"] == str(event.id) and body["changed_fields"] == ["location"]
    [run] = body["executions"]
    assert (run["workflow_name"], run["status"]) == ("Sync", "running")
    assert [(j["operation"], j["status"]) for j in run["jobs"]] == [("update_user", "running")]


def test_other_organizations_events_are_invisible(client: TestClient, db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    employee = create_employee(db_session, acme)
    service = EmployeeService(db_session)
    service.update(acme, employee.id, {"location": "Pune"})
    acme_event = service.recorded_events[0]
    outsider = viewer(db_session, globex)

    hidden = client.get(url(globex, acme_event.id), headers=outsider)

    assert (hidden.status_code, hidden.json()["error"]["code"]) == (404, "event_not_found")
    assert client.get(url(acme), headers=outsider).status_code == 404
    assert client.get(url(globex), headers=outsider).json()["total"] == 0
    assert client.get(url(globex, uuid.uuid4()), headers=outsider).status_code == 404
