"""API tests for workflows: configuration, validation, versioning, activation,
execution history, permissions and tenant isolation."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Connector,
    ConnectorStatus,
    ExecutionStatus,
    IntegrationEvent,
    JobStatus,
    Organization,
    OrganizationRole,
    SynchronizationJob,
    WorkflowExecution,
)
from tests.factories import (
    add_member,
    auth_headers,
    create_connector,
    create_employee,
    create_organization,
    create_user,
)

ADMIN = OrganizationRole.ORG_ADMIN
MANAGER = OrganizationRole.INTEGRATION_MANAGER
VIEWER = OrganizationRole.VIEWER


def url(org: Organization, *parts: object) -> str:
    return "/".join([f"/api/v1/organizations/{org.id}/workflows", *map(str, parts)])


def member(session: Session, org: Organization, role: OrganizationRole = ADMIN) -> dict[str, str]:
    user = create_user(session)
    add_member(session, user, org, role)
    return auth_headers(user)


def step(connector: Connector, operation: str = "create_user") -> dict[str, str]:
    return {"connector_id": str(connector.id), "operation": operation}


def onboarding(*connectors: Connector, name: str = "Onboarding") -> dict[str, Any]:
    return {
        "name": name,
        "description": "Accounts for new hires.",
        "trigger_event_type": "employee.created",
        "steps": [step(c) for c in connectors],
    }


@pytest.fixture
def org(db_session: Session) -> Organization:
    return create_organization(db_session)


@pytest.fixture
def apps(db_session: Session, org: Organization) -> dict[str, Connector]:
    return {
        t: create_connector(db_session, org, connector_type=t, name=t.title())
        for t in ("slack", "google_workspace", "payroll")
    }


def create(client: TestClient, org: Organization, headers: dict, body: dict) -> dict[str, Any]:
    response = client.post(url(org), json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# ---- create and read -----------------------------------------------------------------


def test_create_workflow_starts_inactive_with_ordered_steps(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    body = create(
        client,
        org,
        member(db_session, org),
        onboarding(apps["slack"], apps["google_workspace"], apps["payroll"]),
    )

    assert (body["name"], body["trigger_event_type"]) == ("Onboarding", "employee.created")
    assert (body["is_active"], body["version"]) == (False, 1)
    assert [(s["position"], s["connector_type"], s["operation"]) for s in body["steps"]] == [
        (1, "slack", "create_user"),
        (2, "google_workspace", "create_user"),
        (3, "payroll", "create_user"),
    ]
    assert body["steps"][0]["connector_name"] == "Slack"


def test_list_filters_and_get(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    headers = member(db_session, org)
    first = create(client, org, headers, onboarding(apps["slack"]))
    offboarding = {
        "name": "Offboarding",
        "trigger_event_type": "employee.terminated",
        "steps": [step(apps["slack"], "deactivate_user")],
    }
    create(client, org, headers, offboarding)
    client.post(url(org, first["id"], "activate"), headers=headers)

    def names(**params: str) -> list[str]:
        body = client.get(url(org), params=params, headers=headers).json()
        return [w["name"] for w in body["items"]]

    assert names() == ["Offboarding", "Onboarding"]
    assert names(trigger_event_type="employee.terminated") == ["Offboarding"]
    assert names(is_active="true") == ["Onboarding"]
    assert client.get(url(org, first["id"]), headers=headers).json()["id"] == first["id"]
    missing = client.get(url(org, uuid.uuid4()), headers=headers)
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "workflow_not_found")


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"steps": []}, "validation_error"),
        ({"trigger_event_type": "employee.promoted"}, "validation_error"),
        ({"steps": [{"connector_id": "%s", "operation": "get_user"}]}, "validation_error"),
        ({"name": "   "}, "validation_error"),
        ({"unknown": 1}, "validation_error"),
    ],
)
def test_create_rejects_invalid_input(
    client: TestClient,
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    change: dict[str, Any],
    code: str,
) -> None:
    body = {**onboarding(apps["slack"]), **change}
    if body["steps"] and body["steps"][0]["connector_id"] == "%s":
        body["steps"][0]["connector_id"] = str(apps["slack"].id)

    response = client.post(url(org), json=body, headers=member(db_session, org))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_create_rejects_unknown_foreign_and_duplicate_steps(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    headers = member(db_session, org)
    foreign = create_connector(db_session, create_organization(db_session))

    def error(body: dict) -> tuple[int, str]:
        response = client.post(url(org), json=body, headers=headers)
        return response.status_code, response.json()["error"]["code"]

    unknown = {"connector_id": str(uuid.uuid4()), "operation": "create_user"}
    assert error({**onboarding(apps["slack"]), "steps": [unknown]}) == (
        422,
        "connector_not_found",
    )
    # Another organization's connector looks exactly like an unknown one.
    assert error(onboarding(foreign)) == (422, "connector_not_found")
    assert error(onboarding(apps["slack"], apps["slack"])) == (422, "duplicate_step")


def test_names_are_unique_per_organization(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    headers = member(db_session, org)
    create(client, org, headers, onboarding(apps["slack"]))

    response = client.post(url(org), json=onboarding(apps["payroll"]), headers=headers)

    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "workflow_name_taken",
    )


# ---- update and versioning -----------------------------------------------------------


def test_changing_steps_or_trigger_increments_the_version(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    headers = member(db_session, org)
    workflow = create(client, org, headers, onboarding(apps["slack"], apps["payroll"]))

    def patch(body: dict) -> dict[str, Any]:
        response = client.patch(url(org, workflow["id"]), json=body, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    renamed = patch({"name": "New hires", "description": None})
    assert (renamed["name"], renamed["description"], renamed["version"]) == ("New hires", None, 1)

    same_steps = patch({"steps": [step(apps["slack"]), step(apps["payroll"])]})
    assert same_steps["version"] == 1  # identical list: nothing changed

    reordered = patch({"steps": [step(apps["payroll"]), step(apps["google_workspace"])]})
    assert reordered["version"] == 2
    assert [s["connector_type"] for s in reordered["steps"]] == ["payroll", "google_workspace"]
    assert [s["position"] for s in reordered["steps"]] == [1, 2]

    retriggered = patch({"trigger_event_type": "employee.updated"})
    assert (retriggered["trigger_event_type"], retriggered["version"]) == (
        "employee.updated",
        3,
    )


def test_update_validates_like_create(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    headers = member(db_session, org)
    first = create(client, org, headers, onboarding(apps["slack"]))
    create(client, org, headers, onboarding(apps["payroll"], name="Payroll only"))

    taken = client.patch(url(org, first["id"]), json={"name": "Payroll only"}, headers=headers)
    duplicate = client.patch(
        url(org, first["id"]),
        json={"steps": [step(apps["slack"]), step(apps["slack"])]},
        headers=headers,
    )

    assert (taken.status_code, taken.json()["error"]["code"]) == (409, "workflow_name_taken")
    assert (duplicate.status_code, duplicate.json()["error"]["code"]) == (422, "duplicate_step")
    unchanged = client.get(url(org, first["id"]), headers=headers).json()
    assert (unchanged["name"], len(unchanged["steps"]), unchanged["version"]) == (
        "Onboarding",
        1,
        1,
    )


# ---- activation ----------------------------------------------------------------------


def test_activate_and_deactivate_are_idempotent(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    headers = member(db_session, org)
    workflow = create(client, org, headers, onboarding(apps["slack"]))

    for _ in range(2):
        assert client.post(url(org, workflow["id"], "activate"), headers=headers).json()[
            "is_active"
        ]
    for _ in range(2):
        response = client.post(url(org, workflow["id"], "deactivate"), headers=headers)
        assert response.json()["is_active"] is False


def test_a_workflow_using_a_disconnected_connector_cannot_be_activated(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    headers = member(db_session, org)
    workflow = create(client, org, headers, onboarding(apps["slack"], apps["payroll"]))
    apps["payroll"].status = ConnectorStatus.DISCONNECTED
    db_session.flush()

    response = client.post(url(org, workflow["id"], "activate"), headers=headers)

    assert response.status_code == 409
    error = response.json()["error"]
    assert (error["code"], error["details"]["connectors"]) == (
        "connector_disconnected",
        ["Payroll"],
    )
    assert client.get(url(org, workflow["id"]), headers=headers).json()["is_active"] is False


# ---- execution history ---------------------------------------------------------------


def test_execution_history_shows_per_step_status(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    headers = member(db_session, org)
    workflow = create(client, org, headers, onboarding(apps["slack"], apps["payroll"]))
    employee = create_employee(db_session, org)
    event = IntegrationEvent(
        organization_id=org.id, event_type="employee.created", employee_id=employee.id, payload={}
    )
    db_session.add(event)
    db_session.flush()
    now = datetime.now(UTC)
    execution = WorkflowExecution(
        organization_id=org.id,
        event_id=event.id,
        workflow_id=uuid.UUID(workflow["id"]),
        workflow_version=1,
        status=ExecutionStatus.FAILED,
        started_at=now,
        finished_at=now,
    )
    execution.jobs = [
        SynchronizationJob(
            organization_id=org.id,
            position=1,
            connector_id=apps["slack"].id,
            operation="create_user",
            employee_id=employee.id,
            status=JobStatus.SUCCEEDED,
            attempts=1,
            external_id="U123",
        ),
        SynchronizationJob(
            organization_id=org.id,
            position=2,
            connector_id=apps["payroll"].id,
            operation="create_user",
            employee_id=employee.id,
            status=JobStatus.FAILED,
            attempts=1,
            error_category="server",
            error_message="Simulated failure (503).",
        ),
    ]
    db_session.add(execution)
    db_session.flush()

    page = client.get(url(org, workflow["id"], "executions"), headers=headers).json()
    failed_only = client.get(
        url(org, workflow["id"], "executions"),
        params={"execution_status": "succeeded"},
        headers=headers,
    ).json()

    assert page["total"] == 1 and failed_only["total"] == 0
    [run] = page["items"]
    assert (run["status"], run["event_type"], run["workflow_name"]) == (
        "failed",
        "employee.created",
        "Onboarding",
    )
    assert [(j["position"], j["status"], j["external_id"]) for j in run["jobs"]] == [
        (1, "succeeded", "U123"),
        (2, "failed", None),
    ]
    assert run["jobs"][1]["error_category"] == "server"


# ---- permissions and isolation -------------------------------------------------------


def test_viewers_read_managers_and_admins_configure(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    workflow = create(client, org, member(db_session, org, MANAGER), onboarding(apps["slack"]))
    viewer = member(db_session, org, VIEWER)

    assert client.get(url(org), headers=viewer).status_code == 200
    assert client.get(url(org, workflow["id"], "executions"), headers=viewer).status_code == 200
    for response in (
        client.post(url(org), json=onboarding(apps["payroll"], name="V"), headers=viewer),
        client.patch(url(org, workflow["id"]), json={"name": "V"}, headers=viewer),
        client.post(url(org, workflow["id"], "activate"), headers=viewer),
        client.post(url(org, workflow["id"], "deactivate"), headers=viewer),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["details"]["required_permission"] == "workflows:manage"


def test_other_organizations_workflows_are_invisible(
    client: TestClient, db_session: Session, org: Organization, apps: dict[str, Connector]
) -> None:
    workflow = create(client, org, member(db_session, org), onboarding(apps["slack"]))
    other = create_organization(db_session)
    outsider = member(db_session, other)

    for response in (
        client.get(url(other, workflow["id"]), headers=outsider),
        client.patch(url(other, workflow["id"]), json={"name": "X"}, headers=outsider),
        client.post(url(other, workflow["id"], "activate"), headers=outsider),
        client.get(url(other, workflow["id"], "executions"), headers=outsider),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "workflow_not_found"
    assert client.get(url(org), headers=outsider).status_code == 404
    assert client.get(url(other), headers=outsider).json()["total"] == 0
