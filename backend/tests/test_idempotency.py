"""Idempotency: no duplicate side effects when a request or an external call is repeated.

Outgoing - the workflow engine sends `Idempotency-Key: syncforge-job-<job id>` on
create calls, so a call repeated after a crash or a timeout does not create a second
account (in the mock services, which honour the header).

Incoming - `POST /employees` accepts `Idempotency-Key`, so a client retrying after a
lost response does not create a second employee (and a second onboarding run).
"""

import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.errors import ConnectorError, ErrorCategory
from app.core.config import Settings
from app.events.relay import OutboxRelay
from app.models import (
    AttemptOutcome,
    Connector,
    Employee,
    IdempotencyRecord,
    IntegrationEvent,
    JobStatus,
    Organization,
    OrganizationRole,
    StepOperation,
)
from app.reliability import idempotency
from app.reliability.idempotency import purge_expired
from app.schemas.workflows import StepInput
from app.services.connectors import ConnectorService
from app.services.workflows import WorkflowService
from app.workflows.engine import EventProcessor
from tests.factories import add_member, auth_headers, create_organization, create_user
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock
from tests.test_connector_adapters import GRACE, build
from tests.test_retries import fault, hire, jobs, make_due, noop_publish

TYPES = ["slack", "google_workspace", "payroll"]

# ---- outgoing: the mock services honour Idempotency-Key ---------------------------------


@pytest.mark.parametrize("connector_type", TYPES)
def test_a_repeated_create_with_the_same_key_returns_the_same_user(
    connector_type: str, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    connector = build(connector_type, connector_settings)

    first = connector.create_user(GRACE, idempotency_key="syncforge-job-1")
    second = connector.create_user(GRACE, idempotency_key="syncforge-job-1")

    assert second.external_id == first.external_id
    assert len(mocks[connector_type].state.users) == 1
    creates = [r for r in mocks[connector_type].state.requests if r["method"] == "POST"]
    assert [r["idempotent_replay"] for r in creates][-2:] == [False, True]


@pytest.mark.parametrize("connector_type", TYPES)
def test_without_a_key_a_repeated_create_is_a_conflict(
    connector_type: str, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    connector = build(connector_type, connector_settings)
    connector.create_user(GRACE)

    with pytest.raises(ConnectorError) as raised:
        connector.create_user(GRACE)

    assert raised.value.category is ErrorCategory.CONFLICT


def test_a_key_reused_for_a_different_user_is_refused(
    mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    from dataclasses import replace

    connector = build("slack", connector_settings)
    connector.create_user(GRACE, idempotency_key="k-1")

    with pytest.raises(ConnectorError) as raised:
        connector.create_user(
            replace(GRACE, email="ada@acme.example", employee_number="E-2"), idempotency_key="k-1"
        )

    assert (raised.value.category, raised.value.status_code) == (ErrorCategory.VALIDATION, 422)
    assert len(mocks["slack"].state.users) == 1


# ---- outgoing: the engine ---------------------------------------------------------------


@pytest.fixture
def org(db_session: Session) -> Organization:
    return create_organization(db_session)


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


def test_a_worker_crash_after_the_external_create_does_not_create_a_second_account(
    db_session: Session,
    org: Organization,
    onboarding: dict[str, Connector],
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window the account link cannot close: Google created the user, then the worker
    died before SyncForge recorded it."""
    original = ConnectorService._save_account

    def crash_on_google(self, connector, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if connector.connector_type == "google_workspace":
            raise RuntimeError("worker process killed")
        return original(self, connector, *args, **kwargs)

    monkeypatch.setattr(ConnectorService, "_save_account", crash_on_google)
    event = hire(db_session, org)
    with pytest.raises(RuntimeError):
        EventProcessor(db_session, connector_settings).process(event.id)
    db_session.rollback()
    assert len(mocks["google_workspace"].state.users) == 1  # created on Google's side

    monkeypatch.setattr(ConnectorService, "_save_account", original)
    event.locked_until = datetime.now(UTC) - timedelta(seconds=1)  # the lease expires
    db_session.commit()
    result = EventProcessor(db_session, connector_settings).process(event.id)

    assert result.outcome == "completed"
    _, google, _ = jobs(db_session, event)
    assert google.status is JobStatus.SUCCEEDED
    assert [a.outcome for a in google.attempt_history] == [
        AttemptOutcome.INTERRUPTED,
        AttemptOutcome.SUCCEEDED,
    ]
    [user_id] = mocks["google_workspace"].state.users
    assert google.external_id == user_id  # linked to the account created the first time
    creates = [r for r in mocks["google_workspace"].state.requests if r["method"] == "POST"]
    assert [r["idempotent_replay"] for r in creates if "users" in r["path"]] == [False, True]


def test_a_timed_out_create_is_retried_safely(
    db_session: Session,
    org: Organization,
    onboarding: dict[str, Connector],
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    """The API acts but answers after our read timeout (1 s): we cannot tell whether it
    acted. Retrying with the same key is safe either way."""
    fault(mocks["payroll"], kind="timeout", delay_seconds=2.0, path_prefix="/v1/employees")
    event = hire(db_session, org)
    processor = EventProcessor(db_session, connector_settings)
    relay = OutboxRelay(db_session, noop_publish, connector_settings)

    assert processor.process(event.id).outcome == "retrying"
    _, _, payroll = jobs(db_session, event)
    assert payroll.error_category == "timeout"

    # Retry while payroll is still working on the first request: "in progress", retry later.
    make_due(db_session, event)
    relay.run_once()
    assert processor.process(event.id).outcome == "retrying"
    _, _, payroll = jobs(db_session, event)
    assert (payroll.error_category, payroll.attempt_history[-1].error_code) == (
        "in_progress",
        "idempotency_key_in_use",
    )

    time.sleep(2.0)  # the first request finishes on payroll's side
    make_due(db_session, event)
    relay.run_once()
    assert processor.process(event.id).outcome == "completed"
    _, _, payroll = jobs(db_session, event)
    assert payroll.attempts == 3
    assert len(mocks["payroll"].state.users) == 1  # one payroll record, not two
    assert payroll.external_id in mocks["payroll"].state.users


# ---- incoming: POST /employees ----------------------------------------------------------


def url(org: Organization) -> str:
    return f"/api/v1/organizations/{org.id}/employees"


def admin(session: Session, org: Organization) -> dict[str, str]:
    user = create_user(session)
    add_member(session, user, org, OrganizationRole.ORG_ADMIN)
    return auth_headers(user)


def body(number: str = "E-100", **overrides: object) -> dict[str, object]:
    return {
        "employee_number": number,
        "first_name": "Grace",
        "last_name": "Hopper",
        "email": f"{number.lower()}@acme.example",
        "joining_date": "2026-11-01",
        **overrides,
    }


def count(session: Session, model: type, org: Organization) -> int:
    return session.scalar(
        select(func.count()).select_from(model).where(model.organization_id == org.id)
    )


def test_a_retried_create_returns_the_first_response_and_creates_nothing(
    client: TestClient, db_session: Session, org: Organization
) -> None:
    headers = {**admin(db_session, org), "Idempotency-Key": str(uuid.uuid4())}

    first = client.post(url(org), json=body(), headers=headers)
    second = client.post(url(org), json=body(), headers=headers)

    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json() == first.json()
    assert "idempotent-replayed" not in first.headers
    assert second.headers["Idempotent-Replayed"] == "true"
    assert count(db_session, Employee, org) == 1
    assert count(db_session, IntegrationEvent, org) == 1  # one onboarding, not two


def test_the_same_key_for_a_different_request_is_refused(
    client: TestClient, db_session: Session, org: Organization
) -> None:
    headers = {**admin(db_session, org), "Idempotency-Key": "client-key-1"}
    client.post(url(org), json=body("E-1"), headers=headers)

    response = client.post(url(org), json=body("E-2"), headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "idempotency_key_reused"
    assert count(db_session, Employee, org) == 1


def test_keys_belong_to_one_user(
    client: TestClient, db_session: Session, org: Organization
) -> None:
    key = {"Idempotency-Key": "shared-key"}
    client.post(url(org), json=body(), headers={**admin(db_session, org), **key})

    other = client.post(url(org), json=body(), headers={**admin(db_session, org), **key})

    # Not another user's stored response: a normal request, so a normal duplicate check.
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "employee_number_taken"


def test_a_failed_request_is_not_remembered(
    client: TestClient, db_session: Session, org: Organization
) -> None:
    headers = {**admin(db_session, org), "Idempotency-Key": "fix-and-retry"}

    bad = client.post(url(org), json=body(manager_id=str(uuid.uuid4())), headers=headers)
    fixed = client.post(url(org), json=body(), headers=headers)

    assert bad.status_code == 422
    assert fixed.status_code == 201  # same key, corrected body: accepted


def test_an_identical_concurrent_request_gets_the_winners_response(
    client: TestClient,
    db_session: Session,
    org: Organization,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request B looked up the key before request A committed, so both executed; B's
    insert then hit the unique employee number and B must answer with A's response."""
    headers = {**admin(db_session, org), "Idempotency-Key": "race-key"}
    first = client.post(url(org), json=body(), headers=headers)
    real_lookup = idempotency.IdempotencyStore.lookup
    calls = {"n": 0}

    def stale_first_lookup(self):  # noqa: ANN001, ANN202
        calls["n"] += 1
        return None if calls["n"] == 1 else real_lookup(self)

    monkeypatch.setattr(idempotency.IdempotencyStore, "lookup", stale_first_lookup)
    second = client.post(url(org), json=body(), headers=headers)

    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.headers["Idempotent-Replayed"] == "true"


def test_expired_records_are_ignored_and_purged(
    client: TestClient, db_session: Session, org: Organization
) -> None:
    headers = {**admin(db_session, org), "Idempotency-Key": "old-key"}
    client.post(url(org), json=body("E-1"), headers=headers)
    record = db_session.scalar(select(IdempotencyRecord))
    record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    reused = client.post(url(org), json=body("E-2"), headers=headers)

    assert reused.status_code == 201  # the expired key is free again
    assert count(db_session, Employee, org) == 2
    for stored in db_session.scalars(select(IdempotencyRecord)):
        stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    assert purge_expired(db_session) == 1
    assert db_session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0


@pytest.mark.parametrize("key", ["has space", "x" * 256, ""])
def test_malformed_keys_are_rejected(
    client: TestClient, db_session: Session, org: Organization, key: str
) -> None:
    response = client.post(
        url(org), json=body(), headers={**admin(db_session, org), "Idempotency-Key": key}
    )

    assert response.status_code == 422
    assert count(db_session, Employee, org) == 0


def test_requests_without_a_key_store_nothing(
    client: TestClient, db_session: Session, org: Organization
) -> None:
    response = client.post(url(org), json=body(), headers=admin(db_session, org))

    assert response.status_code == 201
    assert db_session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0
