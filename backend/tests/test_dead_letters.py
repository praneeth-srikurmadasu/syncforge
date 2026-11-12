"""The dead-letter queue: events that failed for good are parked with their error,
can be inspected, and can be replayed (once, by an authorized role) without repeating
the steps that already succeeded."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError
from app.events.relay import OutboxRelay
from app.models import (
    AttemptOutcome,
    Connector,
    DeadLetterEvent,
    DeadLetterReason,
    DeadLetterStatus,
    IntegrationEvent,
    IntegrationEventStatus,
    JobStatus,
    Organization,
    OrganizationRole,
    OutboxEvent,
    StepOperation,
    User,
    Workflow,
)
from app.schemas.workflows import StepInput
from app.services.connectors import ConnectorService
from app.services.dead_letters import DeadLetterService
from app.services.workflows import WorkflowService
from app.workflows.engine import EventProcessor
from tests.factories import add_member, auth_headers, create_organization, create_user
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock
from tests.test_retries import fault, hire, jobs, make_due, noop_publish

TYPES = ("slack", "google_workspace", "payroll")


@pytest.fixture
def org(db_session: Session) -> Organization:
    return create_organization(db_session)


@pytest.fixture
def settings(connector_settings: Settings) -> Settings:
    return connector_settings.model_copy(update={"retry_max_attempts": 3})


@pytest.fixture
def apps(
    db_session: Session, org: Organization, mocks: dict[str, RunningMock], settings: Settings
) -> dict[str, Connector]:
    service = ConnectorService(db_session, settings)
    return {
        t: service.create(org, connector_type=t, name=t, config={}, credentials=MOCK_CREDENTIALS[t])
        for t in TYPES
    }


@pytest.fixture
def onboarding(db_session: Session, org: Organization, apps: dict[str, Connector]) -> Workflow:
    service = WorkflowService(db_session)
    workflow = service.create(
        org,
        name="Onboarding",
        description=None,
        trigger_event_type="employee.created",
        steps=[
            StepInput(connector_id=apps[t].id, operation=StepOperation.CREATE_USER) for t in TYPES
        ],
    )
    return service.set_active(org, workflow.id, active=True)


def member(session: Session, org: Organization, role: OrganizationRole) -> tuple[User, dict]:
    user = create_user(session)
    add_member(session, user, org, role)
    return user, auth_headers(user)


def run_until_settled(session: Session, event: IntegrationEvent, settings: Settings) -> list[str]:
    """Process the event, time-travelling through every backoff, until it settles."""
    processor = EventProcessor(session, settings)
    relay = OutboxRelay(session, noop_publish, settings)
    outcomes = [processor.process(event.id).outcome]
    while outcomes[-1] == "retrying":
        make_due(session, event)
        relay.run_once()
        outcomes.append(processor.process(event.id).outcome)
    return outcomes


def entries(session: Session, event: IntegrationEvent) -> list[DeadLetterEvent]:
    return list(
        session.scalars(
            select(DeadLetterEvent)
            .where(DeadLetterEvent.event_id == event.id)
            .order_by(DeadLetterEvent.dead_lettered_at)
        )
    )


def exhaust_google(
    session: Session, org: Organization, mocks: dict[str, RunningMock], settings: Settings
) -> IntegrationEvent:
    fault(mocks["google_workspace"], kind="status", status=503, count=100, path_prefix="/admin")
    event = hire(session, org)
    assert run_until_settled(session, event, settings) == ["retrying", "retrying", "dead_letter"]
    return event


# ---- dead-lettering --------------------------------------------------------------------


def test_exhausted_retries_park_the_event_with_its_error_preserved(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    onboarding: Workflow,
    mocks: dict[str, RunningMock],
    settings: Settings,
) -> None:
    event = exhaust_google(db_session, org, mocks, settings)

    db_session.refresh(event)
    assert (event.status, event.next_attempt_at) == (IntegrationEventStatus.DEAD_LETTER, None)
    [entry] = entries(db_session, event)
    _, google, payroll = jobs(db_session, event)
    assert entry.status is DeadLetterStatus.OPEN
    assert entry.reason is DeadLetterReason.RETRIES_EXHAUSTED
    assert (entry.job_id, entry.connector_id, entry.operation) == (
        google.id,
        apps["google_workspace"].id,
        "create_user",
    )
    assert (entry.error_category, entry.http_status, entry.attempts, entry.failed_steps) == (
        "server",
        503,
        3,
        1,
    )
    assert entry.error_message.startswith("Gave up after 3 attempts")
    assert payroll.status is JobStatus.SKIPPED  # not attempted after the failure


@pytest.mark.parametrize(("status", "category"), [(403, "authorization"), (400, "validation")])
def test_permanent_failures_are_dead_lettered_at_once(
    db_session: Session,
    org: Organization,
    onboarding: Workflow,
    mocks: dict[str, RunningMock],
    settings: Settings,
    status: int,
    category: str,
) -> None:
    fault(mocks["google_workspace"], kind="status", status=status, path_prefix="/admin")
    event = hire(db_session, org)

    assert run_until_settled(db_session, event, settings) == ["dead_letter"]
    [entry] = entries(db_session, event)
    assert (entry.reason, entry.error_category, entry.http_status, entry.attempts) == (
        DeadLetterReason.NON_RETRYABLE,
        category,
        status,
        1,
    )


def test_a_configuration_failure_is_dead_lettered(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    onboarding: Workflow,
    settings: Settings,
) -> None:
    ConnectorService(db_session, settings).disconnect(org, apps["slack"].id)
    event = hire(db_session, org)

    assert run_until_settled(db_session, event, settings) == ["dead_letter"]
    [entry] = entries(db_session, event)
    assert (entry.reason, entry.error_category, entry.connector_id) == (
        DeadLetterReason.NON_RETRYABLE,
        "configuration",
        apps["slack"].id,
    )


def test_successful_events_are_not_dead_lettered(
    db_session: Session, org: Organization, onboarding: Workflow, settings: Settings
) -> None:
    event = hire(db_session, org)

    assert run_until_settled(db_session, event, settings) == ["completed"]
    assert entries(db_session, event) == []


# ---- replay ------------------------------------------------------------------------------


def test_replay_reruns_only_what_failed_and_completes(
    db_session: Session,
    org: Organization,
    onboarding: Workflow,
    mocks: dict[str, RunningMock],
    settings: Settings,
) -> None:
    event = exhaust_google(db_session, org, mocks, settings)
    [entry] = entries(db_session, event)
    actor, _ = member(db_session, org, OrganizationRole.INTEGRATION_MANAGER)
    mocks["google_workspace"].state.faults.clear()  # the outage is over

    DeadLetterService(db_session).replay(org, entry.id, actor)

    db_session.refresh(event)
    assert (event.status, event.last_error, event.completed_at) == (
        IntegrationEventStatus.PENDING,
        None,
        None,
    )
    assert (entry.status, entry.replayed_by_user_id) == (DeadLetterStatus.REPLAYED, actor.id)
    assert entry.replayed_at is not None
    assert entry.error_message.startswith("Gave up after 3 attempts")  # evidence kept
    slack, google, payroll = jobs(db_session, event)
    assert (slack.status, slack.attempts) == (JobStatus.SUCCEEDED, 1)  # untouched
    assert (google.status, google.attempts, google.attempts_at_last_replay) == (
        JobStatus.PENDING,
        3,
        3,
    )
    assert google.error_message is None
    assert payroll.status is JobStatus.PENDING  # it was skipped because of Google
    # Transactional outbox: the replay committed an unpublished outbox row.
    unpublished = db_session.scalars(
        select(OutboxEvent).where(
            OutboxEvent.event_id == event.id, OutboxEvent.published_at.is_(None)
        )
    ).all()
    assert len(unpublished) == 1

    published: list[str] = []
    relay = OutboxRelay(db_session, lambda event_id, _c: published.append(event_id), settings)
    assert relay.run_once().published == 1 and published == [str(event.id)]
    assert EventProcessor(db_session, settings).process(event.id).outcome == "completed"

    slack, google, payroll = jobs(db_session, event)
    assert [j.status for j in (slack, google, payroll)] == [JobStatus.SUCCEEDED] * 3
    assert [(a.attempt_number, a.outcome) for a in google.attempt_history] == [
        (1, AttemptOutcome.FAILED),
        (2, AttemptOutcome.FAILED),
        (3, AttemptOutcome.FAILED),
        (4, AttemptOutcome.SUCCEEDED),
    ]
    assert slack.attempts == 1  # no second Slack call...
    assert len(mocks["slack"].state.users) == 1  # ...and no second Slack account
    assert len(mocks["google_workspace"].state.users) == 1
    assert len(mocks["payroll"].state.users) == 1
    assert entries(db_session, event) == [entry]  # no new entry: it succeeded


def test_a_replayed_event_gets_a_fresh_retry_budget_and_a_new_entry_if_it_fails_again(
    db_session: Session,
    org: Organization,
    onboarding: Workflow,
    mocks: dict[str, RunningMock],
    settings: Settings,
) -> None:
    event = exhaust_google(db_session, org, mocks, settings)  # the outage continues
    [first] = entries(db_session, event)
    actor, _ = member(db_session, org, OrganizationRole.ORG_ADMIN)

    DeadLetterService(db_session).replay(org, first.id, actor)
    OutboxRelay(db_session, noop_publish, settings).run_once()
    outcomes = run_until_settled(db_session, event, settings)

    assert outcomes == ["retrying", "retrying", "dead_letter"]  # three more attempts, not one
    _, google, _ = jobs(db_session, event)
    assert google.attempts == 6
    old, new = entries(db_session, event)
    assert (old.id, old.status) == (first.id, DeadLetterStatus.REPLAYED)
    assert (new.status, new.attempts, new.reason) == (
        DeadLetterStatus.OPEN,
        3,
        DeadLetterReason.RETRIES_EXHAUSTED,
    )


def test_an_entry_can_be_replayed_only_once(
    db_session: Session,
    org: Organization,
    onboarding: Workflow,
    mocks: dict[str, RunningMock],
    settings: Settings,
) -> None:
    event = exhaust_google(db_session, org, mocks, settings)
    [entry] = entries(db_session, event)
    actor, _ = member(db_session, org, OrganizationRole.ORG_ADMIN)
    service = DeadLetterService(db_session)
    service.replay(org, entry.id, actor)

    with pytest.raises(ConflictError) as raised:
        service.replay(org, entry.id, actor)

    assert raised.value.code == "already_replayed"
    outbox_rows = db_session.scalars(
        select(OutboxEvent).where(OutboxEvent.event_id == event.id)
    ).all()
    assert len(outbox_rows) == 2  # the original event + one replay, not two


def test_replay_is_refused_while_the_failed_workflow_is_inactive(
    db_session: Session,
    org: Organization,
    onboarding: Workflow,
    mocks: dict[str, RunningMock],
    settings: Settings,
) -> None:
    event = exhaust_google(db_session, org, mocks, settings)
    [entry] = entries(db_session, event)
    actor, _ = member(db_session, org, OrganizationRole.ORG_ADMIN)
    WorkflowService(db_session).set_active(org, onboarding.id, active=False)

    with pytest.raises(ConflictError) as raised:
        DeadLetterService(db_session).replay(org, entry.id, actor)

    assert raised.value.code == "workflow_inactive"
    db_session.refresh(entry)
    db_session.refresh(event)
    assert entry.status is DeadLetterStatus.OPEN
    assert event.status is IntegrationEventStatus.DEAD_LETTER


# ---- API ---------------------------------------------------------------------------------


def url(org: Organization, *parts: object) -> str:
    return "/".join([f"/api/v1/organizations/{org.id}/dead-letter-events", *map(str, parts)])


def test_api_lists_and_shows_entries_without_personal_data(
    client: TestClient,
    db_session: Session,
    org: Organization,
    onboarding: Workflow,
    mocks: dict[str, RunningMock],
    settings: Settings,
) -> None:
    event = exhaust_google(db_session, org, mocks, settings)
    _, headers = member(db_session, org, OrganizationRole.VIEWER)

    page = client.get(url(org), headers=headers)
    open_only = client.get(url(org), params={"entry_status": "open"}, headers=headers)
    replayed_only = client.get(url(org), params={"entry_status": "replayed"}, headers=headers)

    assert page.status_code == 200
    assert (page.json()["total"], open_only.json()["total"], replayed_only.json()["total"]) == (
        1,
        1,
        0,
    )
    [item] = page.json()["items"]
    assert (item["event_id"], item["event_type"], item["reason"], item["http_status"]) == (
        str(event.id),
        "employee.created",
        "retries_exhausted",
        503,
    )
    detail = client.get(url(org, item["id"]), headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["event"]["status"] == "dead_letter"
    assert [h["id"] for h in body["history"]] == [item["id"]]
    assert "grace" not in detail.text.lower() and "hopper" not in detail.text.lower()


def test_api_replay_requires_the_replay_permission(
    client: TestClient,
    db_session: Session,
    org: Organization,
    onboarding: Workflow,
    mocks: dict[str, RunningMock],
    settings: Settings,
) -> None:
    event = exhaust_google(db_session, org, mocks, settings)
    [entry] = entries(db_session, event)
    _, viewer = member(db_session, org, OrganizationRole.VIEWER)
    manager, manager_headers = member(db_session, org, OrganizationRole.INTEGRATION_MANAGER)

    refused = client.post(url(org, entry.id, "replay"), headers=viewer)
    accepted = client.post(url(org, entry.id, "replay"), headers=manager_headers)
    again = client.post(url(org, entry.id, "replay"), headers=manager_headers)

    assert refused.status_code == 403
    assert accepted.status_code == 202
    assert (accepted.json()["status"], accepted.json()["replayed_by_user_id"]) == (
        "replayed",
        str(manager.id),
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_replayed"


def test_api_hides_other_organizations_entries(
    client: TestClient,
    db_session: Session,
    org: Organization,
    onboarding: Workflow,
    mocks: dict[str, RunningMock],
    settings: Settings,
) -> None:
    event = exhaust_google(db_session, org, mocks, settings)
    [entry] = entries(db_session, event)
    other = create_organization(db_session)
    _, outsider = member(db_session, other, OrganizationRole.ORG_ADMIN)

    assert client.get(url(other), headers=outsider).json()["total"] == 0
    for response in (
        client.get(url(other, entry.id), headers=outsider),
        client.post(url(other, entry.id, "replay"), headers=outsider),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "dead_letter_not_found"
    assert client.get(url(org), headers=outsider).status_code == 404  # not a member
