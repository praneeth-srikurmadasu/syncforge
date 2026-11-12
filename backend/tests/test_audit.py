"""The audit log: what is recorded (and what never is), who the actor is, atomicity with
the change, append-only enforcement, and the read API."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import audit
from app.core.config import Settings
from app.models import (
    ActorType,
    AuditLog,
    AuditOutcome,
    Connector,
    Organization,
    OrganizationRole,
    StepOperation,
    User,
)
from app.reliability.circuit_breaker import CircuitBreaker
from app.schemas.workflows import StepInput
from app.services.connectors import ConnectorService
from app.services.dead_letters import DeadLetterService
from app.services.workflows import WorkflowService
from app.workflows.engine import EventProcessor
from tests.factories import add_member, auth_headers, create_organization, create_user
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock
from tests.test_retries import fault, hire

TYPES = ("slack", "google_workspace", "payroll")


def entries(session: Session, org: Organization, prefix: str = "") -> list[AuditLog]:
    return list(
        session.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == org.id, AuditLog.action.startswith(prefix))
            .order_by(AuditLog.id)
        )
    )


def actions(session: Session, org: Organization, prefix: str = "") -> list[str]:
    return [e.action for e in entries(session, org, prefix)]


@pytest.fixture
def org(db_session: Session) -> Organization:
    return create_organization(db_session)


@pytest.fixture
def admin(db_session: Session, org: Organization) -> User:
    user = create_user(db_session)
    add_member(db_session, user, org, OrganizationRole.ORG_ADMIN)
    return user


def employees_url(org: Organization, *parts: object) -> str:
    return "/".join([f"/api/v1/organizations/{org.id}/employees", *map(str, parts)])


# ---- user actions through the API --------------------------------------------------------


def test_employee_lifecycle_is_audited_without_personal_values(
    client: TestClient, db_session: Session, org: Organization, admin: User
) -> None:
    headers = auth_headers(admin)
    created = client.post(
        employees_url(org),
        headers={**headers, "X-Request-ID": "audit-demo-1"},
        json={
            "employee_number": "E-77",
            "first_name": "Grace",
            "last_name": "Hopper",
            "email": "grace.hopper@acme.example",
            "designation": "Engineer",
            "joining_date": "2026-11-01",
        },
    ).json()
    client.patch(
        employees_url(org, created["id"]),
        headers=headers,
        json={"first_name": "Gracie", "designation": "Staff Engineer"},
    )
    client.post(employees_url(org, created["id"], "terminate"), headers=headers)
    client.delete(employees_url(org, created["id"]), headers=headers)

    log = entries(db_session, org, "employee.")
    assert [e.action for e in log] == [
        "employee.created",
        "employee.updated",
        "employee.terminated",
        "employee.archived",
    ]
    assert all(e.actor_type is ActorType.USER and e.actor_user_id == admin.id for e in log)
    assert all(e.resource_type == "employee" and e.resource_id == created["id"] for e in log)
    assert log[0].request_id == "audit-demo-1"
    update = log[1].details
    assert update["changed_fields"] == ["designation", "first_name"]
    assert update["values"] == {"designation": {"from": "Engineer", "to": "Staff Engineer"}}
    assert update["events"] == ["employee.updated"]
    stored = json.dumps([e.details for e in log]).lower()
    for personal in ("grace", "gracie", "hopper", "acme.example", "e-77"):
        assert personal not in stored  # names, e-mail, employee number: field names only


def test_a_failed_change_leaves_no_entry(
    client: TestClient, db_session: Session, org: Organization, admin: User
) -> None:
    body = {
        "employee_number": "E-1",
        "first_name": "A",
        "last_name": "B",
        "email": "a.b@acme.example",
        "joining_date": "2026-11-01",
    }
    client.post(employees_url(org), headers=auth_headers(admin), json=body)

    duplicate = client.post(employees_url(org), headers=auth_headers(admin), json=body)

    assert duplicate.status_code == 409
    assert actions(db_session, org, "employee.") == ["employee.created"]  # one, not two


def test_permission_changes_are_audited(
    client: TestClient, db_session: Session, org: Organization, admin: User
) -> None:
    newcomer = create_user(db_session, email="new.member@acme.example")
    base = f"/api/v1/organizations/{org.id}/members"
    headers = auth_headers(admin)

    client.post(base, headers=headers, json={"email": newcomer.email, "role": "viewer"})
    client.patch(f"{base}/{newcomer.id}", headers=headers, json={"role": "integration_manager"})
    client.delete(f"{base}/{newcomer.id}", headers=headers)

    log = entries(db_session, org, "member.")
    assert [(e.action, e.resource_id) for e in log] == [
        ("member.added", str(newcomer.id)),
        ("member.role_changed", str(newcomer.id)),
        ("member.removed", str(newcomer.id)),
    ]
    assert log[1].details == {
        "user_id": str(newcomer.id),
        "from_role": "viewer",
        "to_role": "integration_manager",
    }
    assert all(e.actor_user_id == admin.id for e in log)
    assert "new.member" not in json.dumps([e.details for e in log])


def test_connector_changes_are_audited_without_secrets(
    db_session: Session,
    org: Organization,
    admin: User,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    service = ConnectorService(db_session, connector_settings)
    connector = service.create(
        org, connector_type="slack", name="Slack", config={}, credentials=MOCK_CREDENTIALS["slack"]
    )
    service.update(
        org, connector.id, name=None, config=None, credentials={"token": "xoxp-rotated-secret-1"}
    )
    fault(mocks["slack"], kind="status", status=401)
    service.test(org, connector.id)
    service.disconnect(org, connector.id)

    log = entries(db_session, org, "connector.")
    assert [(e.action, e.outcome) for e in log] == [
        ("connector.created", AuditOutcome.SUCCESS),
        ("connector.updated", AuditOutcome.SUCCESS),
        ("connector.tested", AuditOutcome.FAILURE),
        ("connector.disconnected", AuditOutcome.SUCCESS),
    ]
    assert log[1].details == {"changed": ["credentials"]}
    assert log[2].details["error_category"] == "authentication"
    stored = json.dumps([e.details for e in log])
    assert "xoxp" not in stored and "rotated" not in stored


# ---- system actions in the worker --------------------------------------------------------


@pytest.fixture
def onboarding(
    db_session: Session,
    org: Organization,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> dict[str, Connector]:
    service = ConnectorService(db_session, connector_settings)
    apps = {
        t: service.create(org, connector_type=t, name=t, config={}, credentials=MOCK_CREDENTIALS[t])
        for t in TYPES
    }
    workflows = WorkflowService(db_session)
    workflow = workflows.create(
        org,
        name="Onboarding",
        description=None,
        trigger_event_type="employee.created",
        steps=[
            StepInput(connector_id=apps[t].id, operation=StepOperation.CREATE_USER) for t in TYPES
        ],
    )
    workflows.set_active(org, workflow.id, active=True)
    return apps


def test_workflow_executions_retries_and_dead_letters_are_audited_as_the_system(
    db_session: Session,
    org: Organization,
    admin: User,
    onboarding: dict[str, Connector],
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    assert actions(db_session, org, "workflow.") == ["workflow.created", "workflow.activated"]
    processor = EventProcessor(db_session, connector_settings)

    processor.process(hire(db_session, org).id)  # succeeds
    fault(mocks["payroll"], kind="status", status=503, path_prefix="/v1/employees")
    processor.process(hire(db_session, org).id)  # payroll 503: retry scheduled
    fault(mocks["google_workspace"], kind="status", status=403, path_prefix="/admin")
    failing = hire(db_session, org)
    processor.process(failing.id)  # Google 403: dead letter

    worker_actions = {"workflow.executed", "sync.retry_scheduled", "event.dead_lettered"}
    system = [e for e in entries(db_session, org) if e.action in worker_actions]
    assert [(e.action, e.outcome) for e in system] == [
        ("workflow.executed", AuditOutcome.SUCCESS),
        ("sync.retry_scheduled", AuditOutcome.FAILURE),
        ("workflow.executed", AuditOutcome.FAILURE),
        ("event.dead_lettered", AuditOutcome.FAILURE),
    ]
    assert all(e.actor_type is ActorType.SYSTEM and e.actor_user_id is None for e in system)
    retry = system[1].details
    assert (retry["operation"], retry["attempt"], retry["error_category"]) == (
        "create_user",
        1,
        "server",
    )
    failed = system[2].details
    assert (failed["failed_position"], failed["error_category"]) == (2, "authorization")
    assert failed["steps"] == {"succeeded": 1, "failed": 1, "skipped": 1}
    assert system[3].resource_id == str(failing.id)

    # A person replays it: the replay is that person's action.
    audit.set_actor(db_session, admin.id)
    entry_id = uuid.UUID(system[3].details["dead_letter_id"])
    DeadLetterService(db_session).replay(org, entry_id, admin)
    [replayed] = entries(db_session, org, "dead_letter.")
    assert (replayed.actor_type, replayed.actor_user_id, replayed.details["event_id"]) == (
        ActorType.USER,
        admin.id,
        str(failing.id),
    )


def test_circuit_breaker_transitions_are_audited(
    db_session: Session, org: Organization, onboarding: dict[str, Connector], settings_low: Settings
) -> None:
    from app.connectors.errors import ConnectorError, ErrorCategory

    breaker = CircuitBreaker(db_session, settings_low)
    slack = onboarding["slack"]
    outage = ConnectorError(ErrorCategory.SERVER, "down", "http_503", 503)
    breaker.record(slack, outage)
    breaker.record(slack, outage)  # opens
    breaker.reset(slack)  # e.g. after a successful connection test

    log = entries(db_session, org, "connector.circuit")
    assert [(e.action, e.outcome) for e in log] == [
        ("connector.circuit_opened", AuditOutcome.FAILURE),
        ("connector.circuit_closed", AuditOutcome.SUCCESS),
    ]
    assert log[0].details["consecutive_failures"] == 2
    assert log[1].details["reason"] == "connection_test"


@pytest.fixture
def settings_low(connector_settings: Settings) -> Settings:
    return connector_settings.model_copy(update={"circuit_failure_threshold": 2})


# ---- append-only -------------------------------------------------------------------------


def first_entry(session: Session, org: Organization) -> AuditLog:
    entry = audit.record(
        session,
        organization_id=org.id,
        action="organization.renamed",
        resource_type="organization",
        resource_id=org.id,
        details={"from": "a", "to": "b"},
    )
    session.commit()
    return entry


def test_entries_cannot_be_updated(db_session: Session, org: Organization) -> None:
    entry = first_entry(db_session, org)

    with pytest.raises(DBAPIError, match="append-only"), db_session.begin_nested():
        db_session.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"), {"id": entry.id}
        )


def test_entries_cannot_be_deleted_except_by_an_explicit_retention_transaction(
    db_session: Session, org: Organization
) -> None:
    entry = first_entry(db_session, org)

    with pytest.raises(DBAPIError, match="append-only"), db_session.begin_nested():
        db_session.execute(delete(AuditLog).where(AuditLog.id == entry.id))

    with db_session.begin_nested():
        db_session.execute(text("SET LOCAL syncforge.allow_audit_delete = 'on'"))
        db_session.execute(delete(AuditLog).where(AuditLog.id == entry.id))
    assert db_session.get(AuditLog, entry.id) is None


def test_deleting_a_user_keeps_their_history(
    client: TestClient, db_session: Session, org: Organization
) -> None:
    leaver = create_user(db_session)
    add_member(db_session, leaver, org, OrganizationRole.ORG_ADMIN)
    client.patch(
        f"/api/v1/organizations/{org.id}", headers=auth_headers(leaver), json={"name": "Renamed"}
    )
    [renamed] = entries(db_session, org, "organization.renamed")

    db_session.delete(leaver)
    db_session.flush()

    db_session.refresh(renamed)
    assert (renamed.actor_type, renamed.actor_user_id) == (ActorType.USER, None)
    assert renamed.details["to"] == "Renamed"


# ---- the API -----------------------------------------------------------------------------


def audit_url(org: Organization) -> str:
    return f"/api/v1/organizations/{org.id}/audit-logs"


def test_api_filters_and_orders_newest_first(
    client: TestClient, db_session: Session, org: Organization, admin: User
) -> None:
    headers = auth_headers(admin)
    for number in ("E-1", "E-2"):
        client.post(
            employees_url(org),
            headers=headers,
            json={
                "employee_number": number,
                "first_name": "A",
                "last_name": "B",
                "email": f"{number.lower()}@acme.example",
                "joining_date": "2026-11-01",
            },
        )
    client.patch(f"/api/v1/organizations/{org.id}", headers=headers, json={"name": "New name"})

    everything = client.get(audit_url(org), headers=headers).json()
    employees = client.get(audit_url(org), params={"action": "employee."}, headers=headers).json()
    renames = client.get(
        audit_url(org), params={"action": "organization.renamed"}, headers=headers
    ).json()
    one = client.get(
        audit_url(org),
        params={"resource_type": "employee", "resource_id": employees["items"][0]["resource_id"]},
        headers=headers,
    ).json()

    assert everything["items"][0]["action"] == "organization.renamed"  # newest first
    ids = [i["id"] for i in everything["items"]]
    assert ids == sorted(ids, reverse=True)
    assert employees["total"] == 2
    assert renames["total"] == 1 and renames["items"][0]["details"]["to"] == "New name"
    assert one["total"] == 1
    assert {i["actor_user_id"] for i in employees["items"]} == {str(admin.id)}


@pytest.mark.parametrize(
    ("role", "status"),
    [
        (OrganizationRole.VIEWER, 403),
        (OrganizationRole.INTEGRATION_MANAGER, 200),
        (OrganizationRole.ORG_ADMIN, 200),
    ],
)
def test_api_requires_audit_read(
    client: TestClient, db_session: Session, org: Organization, role: OrganizationRole, status: int
) -> None:
    user = create_user(db_session)
    add_member(db_session, user, org, role)

    assert client.get(audit_url(org), headers=auth_headers(user)).status_code == status


def test_api_shows_only_the_organizations_own_entries(
    client: TestClient, db_session: Session, org: Organization, admin: User
) -> None:
    other = create_organization(db_session)
    outsider = create_user(db_session)
    add_member(db_session, outsider, other, OrganizationRole.ORG_ADMIN)
    client.patch(f"/api/v1/organizations/{org.id}", headers=auth_headers(admin), json={"name": "X"})

    assert client.get(audit_url(org), headers=auth_headers(outsider)).status_code == 404
    theirs = client.get(audit_url(other), headers=auth_headers(outsider)).json()
    assert all(i["action"] != "organization.renamed" for i in theirs["items"])
