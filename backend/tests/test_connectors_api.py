"""API tests for connectors: configuration, encrypted credentials, connection tests,
operations against the running mock services, permissions and tenant isolation."""

import logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.connectors import get_connector_settings
from app.core.config import Settings
from app.models import ConnectorCredential, EmploymentStatus, Organization, OrganizationRole
from app.security.encryption import CredentialCipher
from tests.factories import (
    add_member,
    auth_headers,
    create_department,
    create_employee,
    create_organization,
    create_user,
)
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock

ADMIN = OrganizationRole.ORG_ADMIN
MANAGER = OrganizationRole.INTEGRATION_MANAGER
VIEWER = OrganizationRole.VIEWER
SLACK_TOKEN = MOCK_CREDENTIALS["slack"]["token"]


@pytest.fixture
def api(
    client: TestClient, mocks: dict[str, RunningMock], connector_settings: Settings
) -> Iterator[TestClient]:
    """Test client whose connectors call the running mock services."""
    from app.main import app

    app.dependency_overrides[get_connector_settings] = lambda: connector_settings
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_connector_settings, None)


def url(org: Organization, *parts: object) -> str:
    return "/".join([f"/api/v1/organizations/{org.id}/connectors", *map(str, parts)])


def member(session: Session, org: Organization, role: OrganizationRole = ADMIN) -> dict[str, str]:
    user = create_user(session)
    add_member(session, user, org, role)
    return auth_headers(user)


def create_connector(
    api: TestClient,
    org: Organization,
    headers: dict[str, str],
    connector_type: str = "slack",
    credentials: dict[str, str] | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    response = api.post(
        url(org),
        json={
            "connector_type": connector_type,
            "name": name or f"{connector_type} connector",
            "credentials": credentials or MOCK_CREDENTIALS[connector_type],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---- catalog -------------------------------------------------------------------------


def test_catalog_lists_every_connector_type(api: TestClient, db_session: Session) -> None:
    headers = auth_headers(create_user(db_session))

    types = {
        t["connector_type"]: t for t in api.get("/api/v1/connector-types", headers=headers).json()
    }

    assert set(types) == {"slack", "google_workspace", "payroll"}
    assert all(t["simulated"] for t in types.values())
    assert types["google_workspace"]["auth_type"] == "oauth2_client_credentials"
    assert types["slack"]["credentials_schema"]["properties"]["token"]["format"] == "password"
    assert "create_user" in types["payroll"]["operations"]
    assert api.get("/api/v1/connector-types").status_code == 401


# ---- create and credentials ----------------------------------------------------------


def test_create_connector_encrypts_credentials_and_never_returns_them(
    api: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)

    response = api.post(
        url(org),
        json={
            "connector_type": "slack",
            "name": "  Slack  ",
            "credentials": {"token": SLACK_TOKEN},
        },
        headers=member(db_session, org),
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["status"], body["version"]) == ("Slack", "pending", "1.0.0")
    assert body["credentials"]["auth_type"] == "bearer_token"
    assert body["credentials"]["fingerprint"] == "..." + SLACK_TOKEN[-4:]
    assert SLACK_TOKEN not in response.text

    stored = db_session.scalar(select(ConnectorCredential))
    assert SLACK_TOKEN not in stored.encrypted_secret
    assert CredentialCipher.from_settings().decrypt(stored.encrypted_secret) == {
        "token": SLACK_TOKEN
    }


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        ({"connector_type": "teams", "credentials": {}}, 422, "unknown_connector_type"),
        ({"connector_type": "slack", "credentials": {}}, 422, "invalid_connector_settings"),
        (
            {"connector_type": "slack", "credentials": {"token": "xoxp-ok-token", "x": 1}},
            422,
            "invalid_connector_settings",
        ),
        (
            {
                "connector_type": "slack",
                "config": {"base_url": "http://169.254.169.254/latest"},
                "credentials": {"token": "xoxp-ok-token"},
            },
            422,
            "host_not_allowed",
        ),
    ],
)
def test_create_rejects_bad_settings(
    api: TestClient, db_session: Session, payload: dict[str, Any], status: int, code: str
) -> None:
    org = create_organization(db_session)

    response = api.post(url(org), json={"name": "X", **payload}, headers=member(db_session, org))

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "xoxp-ok-token" not in response.text  # submitted secrets are never echoed


def test_validation_errors_name_fields_not_values(api: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)

    response = api.post(
        url(org),
        json={
            "connector_type": "google_workspace",
            "name": "G",
            "credentials": {"client_id": "abc"},
        },
        headers=member(db_session, org),
    )

    fields = {d["field"] for d in response.json()["error"]["details"]}
    assert fields == {"credentials.client_secret"}


def test_connector_names_are_unique_per_organization(api: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org)
    create_connector(api, org, headers, name="Slack")

    response = api.post(
        url(org),
        json={
            "connector_type": "payroll",
            "name": "Slack",
            "credentials": MOCK_CREDENTIALS["payroll"],
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "connector_name_taken"


def test_missing_encryption_key_is_a_clear_503(
    api: TestClient, db_session: Session, connector_settings: Settings
) -> None:
    from app.main import app

    no_key = connector_settings.model_copy(update={"connector_encryption_key": None})
    app.dependency_overrides[get_connector_settings] = lambda: no_key
    org = create_organization(db_session)

    response = api.post(
        url(org),
        json={"connector_type": "slack", "name": "S", "credentials": {"token": SLACK_TOKEN}},
        headers=member(db_session, org),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "encryption_not_configured"


# ---- connection tests ----------------------------------------------------------------


@pytest.mark.parametrize("connector_type", ["slack", "google_workspace", "payroll"])
def test_successful_connection_test(
    api: TestClient, db_session: Session, connector_type: str
) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org)
    connector = create_connector(api, org, headers, connector_type)

    result = api.post(url(org, connector["id"], "test"), headers=headers).json()

    assert result["ok"] is True and result["status"] == "connected" and result["error"] is None
    stored = api.get(url(org, connector["id"]), headers=headers).json()
    assert stored["status"] == "connected" and stored["last_tested_at"] is not None


def test_failed_connection_test_records_the_normalized_error(
    api: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org)
    connector = create_connector(api, org, headers, credentials={"token": "xoxp-wrong-token"})

    response = api.post(url(org, connector["id"], "test"), headers=headers)

    assert response.status_code == 200  # the test ran; it reports failure in the body
    result = response.json()
    assert result["ok"] is False and result["status"] == "error"
    assert result["error"]["category"] == "authentication"
    assert result["error"]["retryable"] is False
    stored = api.get(url(org, connector["id"]), headers=headers).json()
    assert stored["last_error"]["category"] == "authentication"


def test_rate_limited_connection_test_reports_retry_after(
    api: TestClient, db_session: Session, mocks: dict[str, RunningMock]
) -> None:
    from mockservices.faults import FaultSpec

    org = create_organization(db_session)
    headers = member(db_session, org)
    connector = create_connector(api, org, headers, "payroll")
    mocks["payroll"].state.faults.append(FaultSpec(kind="rate_limit", retry_after=30))

    error = api.post(url(org, connector["id"], "test"), headers=headers).json()["error"]

    assert (error["category"], error["retry_after"], error["retryable"]) == (
        "rate_limited",
        30.0,
        True,
    )


# ---- update, rotation, disconnect ----------------------------------------------------


def test_rotating_credentials_fixes_a_broken_connector(
    api: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org)
    connector = create_connector(api, org, headers, credentials={"token": "xoxp-wrong-token"})
    api.post(url(org, connector["id"], "test"), headers=headers)

    updated = api.patch(
        url(org, connector["id"]), json={"credentials": {"token": SLACK_TOKEN}}, headers=headers
    ).json()

    assert updated["status"] == "pending" and updated["last_error"] is None
    assert updated["credentials"]["fingerprint"] == "..." + SLACK_TOKEN[-4:]
    assert api.post(url(org, connector["id"], "test"), headers=headers).json()["ok"] is True


def test_rename_keeps_credentials_and_status(api: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org)
    connector = create_connector(api, org, headers)
    api.post(url(org, connector["id"], "test"), headers=headers)

    renamed = api.patch(
        url(org, connector["id"]), json={"name": "Slack EU"}, headers=headers
    ).json()

    assert (renamed["name"], renamed["status"]) == ("Slack EU", "connected")
    assert renamed["credentials"] is not None


def test_disconnect_revokes_and_credentials_reconnect(api: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org)
    connector = create_connector(api, org, headers)

    first = api.post(url(org, connector["id"], "disconnect"), headers=headers)
    second = api.post(url(org, connector["id"], "disconnect"), headers=headers)  # idempotent

    assert first.json()["status"] == second.json()["status"] == "disconnected"
    assert first.json()["credentials"] is None
    assert db_session.scalar(select(ConnectorCredential)) is None
    blocked = api.post(url(org, connector["id"], "test"), headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "connector_disconnected"

    reconnected = api.patch(
        url(org, connector["id"]), json={"credentials": {"token": SLACK_TOKEN}}, headers=headers
    ).json()
    assert reconnected["status"] == "pending"
    assert api.post(url(org, connector["id"], "test"), headers=headers).json()["ok"] is True


# ---- operations ----------------------------------------------------------------------


@pytest.mark.parametrize("connector_type", ["slack", "google_workspace", "payroll"])
def test_operations_provision_and_deprovision_an_employee(
    api: TestClient, db_session: Session, mocks: dict[str, RunningMock], connector_type: str
) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org)
    employee = create_employee(
        db_session, org, department=create_department(db_session, org, "Eng")
    )
    connector = create_connector(api, org, headers, connector_type)
    ops = url(org, connector["id"], "operations")

    def run(operation: str) -> dict[str, Any]:
        response = api.post(
            ops, json={"operation": operation, "employee_id": str(employee.id)}, headers=headers
        )
        assert response.status_code == 200, response.text
        return response.json()

    created = run("create_user")
    assert created["external_active"] is True and created["account_status"] == "active"
    assert created["external_id"] in mocks[connector_type].state.users

    assert run("update_user")["external_id"] == created["external_id"]
    deactivated = run("deactivate_user")
    assert deactivated["external_active"] is False
    assert deactivated["account_status"] == "deactivated"
    assert run("get_user")["external_active"] is False

    accounts = api.get(url(org, connector["id"], "accounts"), headers=headers).json()
    assert [(a["employee_id"], a["external_id"], a["status"]) for a in accounts["items"]] == [
        (str(employee.id), created["external_id"], "deactivated")
    ]


def test_operation_preconditions(api: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org)
    employee = create_employee(db_session, org)
    gone = create_employee(
        db_session,
        org,
        employment_status=EmploymentStatus.TERMINATED,
        termination_date=employee.joining_date,
    )
    connector = create_connector(api, org, headers)
    ops = url(org, connector["id"], "operations")

    def run(operation: str, employee_id: uuid.UUID) -> tuple[int, str]:
        response = api.post(
            ops, json={"operation": operation, "employee_id": str(employee_id)}, headers=headers
        )
        return response.status_code, response.json().get("error", {}).get("code", "")

    assert run("update_user", employee.id) == (409, "not_linked")
    assert run("create_user", gone.id) == (409, "employee_terminated")
    assert run("create_user", uuid.uuid4()) == (422, "employee_not_found")
    assert run("create_user", employee.id)[0] == 200
    assert run("create_user", employee.id) == (409, "already_linked")

    api.post(url(org, connector["id"], "disconnect"), headers=headers)
    assert run("get_user", employee.id) == (409, "connector_disconnected")


@pytest.mark.parametrize(
    ("fault", "category", "retryable"),
    [
        ({"kind": "status", "status": 503}, "server", True),
        ({"kind": "status", "status": 400}, "validation", False),
        ({"kind": "rate_limit", "retry_after": 5}, "rate_limited", True),
    ],
)
def test_external_failures_are_502_with_normalized_details(
    api: TestClient,
    db_session: Session,
    mocks: dict[str, RunningMock],
    fault: dict[str, Any],
    category: str,
    retryable: bool,
) -> None:
    from mockservices.faults import FaultSpec

    org = create_organization(db_session)
    headers = member(db_session, org)
    employee = create_employee(db_session, org)
    connector = create_connector(api, org, headers)
    mocks["slack"].state.faults.append(FaultSpec(**fault))

    response = api.post(
        url(org, connector["id"], "operations"),
        json={"operation": "create_user", "employee_id": str(employee.id)},
        headers=headers,
    )

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["code"] == "connector_error"
    assert (error["details"]["category"], error["details"]["retryable"]) == (category, retryable)
    # Nothing was linked, so a retry can create the account cleanly.
    assert api.get(url(org, connector["id"], "accounts"), headers=headers).json()["total"] == 0


# ---- permissions, isolation, logging -------------------------------------------------


def test_viewers_can_read_but_not_manage(api: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    connector = create_connector(api, org, member(db_session, org))
    viewer = member(db_session, org, VIEWER)

    assert api.get(url(org), headers=viewer).status_code == 200
    assert api.get(url(org, connector["id"]), headers=viewer).status_code == 200
    for response in (
        api.post(
            url(org),
            json={"connector_type": "slack", "name": "V", "credentials": {}},
            headers=viewer,
        ),
        api.patch(url(org, connector["id"]), json={"name": "V"}, headers=viewer),
        api.post(url(org, connector["id"], "test"), headers=viewer),
        api.post(url(org, connector["id"], "disconnect"), headers=viewer),
        api.post(
            url(org, connector["id"], "operations"),
            json={"operation": "get_user", "employee_id": str(uuid.uuid4())},
            headers=viewer,
        ),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["details"]["required_permission"] == "connectors:manage"


def test_integration_managers_can_manage_connectors(api: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org, MANAGER)

    connector = create_connector(api, org, headers)

    assert api.post(url(org, connector["id"], "test"), headers=headers).json()["ok"] is True


def test_other_organizations_connectors_and_employees_are_invisible(
    api: TestClient, db_session: Session
) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    acme_admin, globex_admin = member(db_session, acme), member(db_session, globex)
    globex_connector = create_connector(api, globex, globex_admin)
    acme_connector = create_connector(api, acme, acme_admin)
    globex_employee = create_employee(db_session, globex)

    for response in (
        api.get(url(acme, globex_connector["id"]), headers=acme_admin),
        api.post(url(acme, globex_connector["id"], "test"), headers=acme_admin),
        api.post(url(acme, globex_connector["id"], "disconnect"), headers=acme_admin),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "connector_not_found"
    assert api.get(url(globex), headers=acme_admin).status_code == 404

    # Acme's connector cannot act on Globex's employee.
    response = api.post(
        url(acme, acme_connector["id"], "operations"),
        json={"operation": "create_user", "employee_id": str(globex_employee.id)},
        headers=acme_admin,
    )
    assert (response.status_code, response.json()["error"]["code"]) == (422, "employee_not_found")


def test_logs_never_contain_credentials(
    api: TestClient, db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    org = create_organization(db_session)
    headers = member(db_session, org)
    connector = create_connector(api, org, headers)
    api.post(url(org, connector["id"], "test"), headers=headers)
    api.patch(
        url(org, connector["id"]),
        json={"credentials": {"token": "xoxp-rotated-1234"}},
        headers=headers,
    )

    assert any(r.getMessage() == "connector test succeeded" for r in caplog.records)
    for record in caplog.records:
        text = str(vars(record))
        assert SLACK_TOKEN not in text and "xoxp-rotated-1234" not in text
