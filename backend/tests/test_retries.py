"""Retries: the backoff policy, the engine's retry decisions, the relay's dispatch of due
retries, the attempt history and its API."""

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.events.relay import OutboxRelay
from app.models import (
    AttemptOutcome,
    Connector,
    ExecutionStatus,
    IntegrationEvent,
    IntegrationEventStatus,
    JobStatus,
    Organization,
    OrganizationRole,
    StepOperation,
    SynchronizationJob,
    WorkflowExecution,
)
from app.reliability.retry import RetryPolicy, decide
from app.schemas.employees import EmployeeCreate
from app.schemas.workflows import StepInput
from app.services.connectors import ConnectorService
from app.services.employees import EmployeeService
from app.services.workflows import WorkflowService
from app.workflows.engine import EventProcessor
from tests.factories import add_member, auth_headers, create_organization, create_user
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock

TYPES = ("slack", "google_workspace", "payroll")

# ---- the policy (pure) ---------------------------------------------------------------


def test_backoff_doubles_from_the_base_delay_and_is_capped() -> None:
    policy = RetryPolicy(base_delay_seconds=2, max_delay_seconds=20, jitter_ratio=0)

    assert [policy.delay(n) for n in range(1, 7)] == [2, 4, 8, 16, 20, 20]


def test_jitter_stays_within_its_ratio_and_actually_varies() -> None:
    policy = RetryPolicy(base_delay_seconds=2, jitter_ratio=0.2)
    rng = random.Random(42)  # noqa: S311 - deterministic jitter for the test

    delays = [policy.delay(3, rng=rng) for _ in range(500)]  # base 8 s

    assert all(6.4 <= d <= 9.6 for d in delays)
    assert len({round(d, 3) for d in delays}) > 100  # not all retries in the same second


def test_retry_after_is_respected_but_capped() -> None:
    policy = RetryPolicy(base_delay_seconds=2, max_delay_seconds=300, jitter_ratio=0)

    assert policy.delay(1, retry_after=30) == 30  # longer than the backoff: honoured
    assert policy.delay(4, retry_after=1) == 16  # shorter than the backoff: backoff wins
    assert policy.delay(1, retry_after=7200) == 300  # never parks a job for hours


@pytest.mark.parametrize(
    ("attempts_made", "retryable", "retry", "reason"),
    [
        (1, True, True, "retryable"),
        (4, True, True, "retryable"),
        (5, True, False, "attempts_exhausted"),
        (1, False, False, "not_retryable"),
    ],
)
def test_decide(attempts_made: int, retryable: bool, retry: bool, reason: str) -> None:
    decision = decide(
        RetryPolicy(max_attempts=5, jitter_ratio=0),
        attempts_made=attempts_made,
        retryable=retryable,
    )

    assert (decision.retry, decision.reason) == (retry, reason)
    assert (decision.delay_seconds is not None) is retry


# ---- the engine and the relay --------------------------------------------------------


@pytest.fixture
def org(db_session: Session) -> Organization:
    return create_organization(db_session)


@pytest.fixture
def apps(
    db_session: Session,
    org: Organization,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> dict[str, Connector]:
    service = ConnectorService(db_session, connector_settings)
    return {
        t: service.create(org, connector_type=t, name=t, config={}, credentials=MOCK_CREDENTIALS[t])
        for t in TYPES
    }


@pytest.fixture
def onboarding(db_session: Session, org: Organization, apps: dict[str, Connector]) -> None:
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
    service.set_active(org, workflow.id, active=True)


def hire(session: Session, org: Organization) -> IntegrationEvent:
    service = EmployeeService(session)
    number = uuid.uuid4().hex[:6]
    service.create(
        org,
        EmployeeCreate(
            employee_number=f"E-{number}",
            first_name="Grace",
            last_name="Hopper",
            email=f"grace.{number}@acme.example",
            joining_date="2026-11-01",
        ),
    )
    return service.recorded_events[0]


def jobs(session: Session, event: IntegrationEvent) -> list[SynchronizationJob]:
    execution = session.scalar(
        select(WorkflowExecution).where(WorkflowExecution.event_id == event.id)
    )
    session.refresh(execution)
    return list(execution.jobs)


def fault(mock: RunningMock, **spec: object) -> None:
    from mockservices.faults import FaultSpec

    mock.state.faults.append(FaultSpec(**spec))


def make_due(session: Session, event: IntegrationEvent) -> None:
    """Time travel: the waiting step's backoff is over."""
    past = datetime.now(UTC) - timedelta(seconds=1)
    for job in jobs(session, event):
        if job.status is JobStatus.RETRYING:
            job.next_attempt_at = past
    event.next_attempt_at = past
    session.commit()


def noop_publish(_event_id: str, _correlation_id: str | None) -> None:
    pass


def test_a_transient_failure_is_retried_after_a_backoff_and_then_succeeds(
    db_session: Session,
    org: Organization,
    onboarding: None,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    fault(mocks["google_workspace"], kind="status", status=503, path_prefix="/admin")
    event = hire(db_session, org)
    processor = EventProcessor(db_session, connector_settings)
    relay = OutboxRelay(db_session, noop_publish, connector_settings)

    first = processor.process(event.id)

    assert first.outcome == "retrying"
    db_session.refresh(event)
    slack, google, payroll = jobs(db_session, event)
    assert slack.status is JobStatus.SUCCEEDED
    assert (google.status, google.attempts, google.error_category) == (
        JobStatus.RETRYING,
        1,
        "server",
    )
    # First retry after ~2 s (base delay) with +/-20 % jitter.
    wait = (google.next_attempt_at - google.finished_at).total_seconds()
    assert 1.6 <= wait <= 2.4
    assert event.status is IntegrationEventStatus.RETRYING
    assert event.next_attempt_at == google.next_attempt_at and event.completed_at is None
    assert payroll.status is JobStatus.PENDING  # sequential: waits for Google
    assert mocks["payroll"].state.users == {}

    assert relay.run_once().retries == 0  # not due yet
    make_due(db_session, event)
    assert relay.run_once().retries == 1  # due: re-dispatched as pending
    db_session.refresh(event)
    assert event.status is IntegrationEventStatus.PENDING

    second = processor.process(event.id)

    assert second.outcome == "completed"
    slack, google, payroll = jobs(db_session, event)
    assert [j.status for j in (slack, google, payroll)] == [JobStatus.SUCCEEDED] * 3
    assert google.attempts == 2 and google.next_attempt_at is None
    assert [(a.attempt_number, a.outcome) for a in google.attempt_history] == [
        (1, AttemptOutcome.FAILED),
        (2, AttemptOutcome.SUCCEEDED),
    ]
    failed_attempt = google.attempt_history[0]
    assert (failed_attempt.http_status, failed_attempt.retryable) == (503, True)
    assert failed_attempt.next_attempt_at is not None
    assert len(mocks["google_workspace"].state.users) == 1  # created exactly once


def test_attempts_are_exhausted_after_the_configured_maximum(
    db_session: Session,
    org: Organization,
    onboarding: None,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    settings = connector_settings.model_copy(update={"retry_max_attempts": 3})
    fault(mocks["google_workspace"], kind="status", status=503, count=10, path_prefix="/admin")
    event = hire(db_session, org)
    processor = EventProcessor(db_session, settings)
    relay = OutboxRelay(db_session, noop_publish, settings)

    outcomes = [processor.process(event.id).outcome]
    while outcomes[-1] == "retrying":
        make_due(db_session, event)
        relay.run_once()
        outcomes.append(processor.process(event.id).outcome)

    assert outcomes == ["retrying", "retrying", "dead_letter"]
    _, google, payroll = jobs(db_session, event)
    assert (google.status, google.attempts) == (JobStatus.FAILED, 3)
    assert google.error_message.startswith("Gave up after 3 attempts")
    assert [a.outcome for a in google.attempt_history] == [AttemptOutcome.FAILED] * 3
    assert google.attempt_history[-1].next_attempt_at is None  # no fourth attempt scheduled
    assert payroll.status is JobStatus.SKIPPED
    db_session.refresh(event)
    assert (event.status, event.next_attempt_at) == (IntegrationEventStatus.DEAD_LETTER, None)
    execution = db_session.scalar(
        select(WorkflowExecution).where(WorkflowExecution.event_id == event.id)
    )
    assert execution.status is ExecutionStatus.FAILED


@pytest.mark.parametrize(("status", "category"), [(403, "authorization"), (400, "validation")])
def test_permanent_failures_are_not_retried(
    db_session: Session,
    org: Organization,
    onboarding: None,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
    status: int,
    category: str,
) -> None:
    fault(mocks["google_workspace"], kind="status", status=status, path_prefix="/admin")
    event = hire(db_session, org)

    result = EventProcessor(db_session, connector_settings).process(event.id)

    assert result.outcome == "dead_letter"
    _, google, _ = jobs(db_session, event)
    assert (google.status, google.attempts, google.error_category) == (
        JobStatus.FAILED,
        1,
        category,
    )
    [attempt] = google.attempt_history
    assert (attempt.retryable, attempt.next_attempt_at) == (False, None)


def test_rate_limit_waits_at_least_retry_after(
    db_session: Session,
    org: Organization,
    onboarding: None,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    fault(mocks["slack"], kind="rate_limit", retry_after=60, path_prefix="/scim/v2/Users")
    event = hire(db_session, org)

    EventProcessor(db_session, connector_settings).process(event.id)

    slack, google, _ = jobs(db_session, event)
    assert (slack.status, slack.error_category) == (JobStatus.RETRYING, "rate_limited")
    assert (slack.next_attempt_at - slack.finished_at).total_seconds() >= 60
    assert slack.attempt_history[0].retry_after_seconds == 60
    assert google.status is JobStatus.PENDING


def test_timeouts_are_retried(
    db_session: Session,
    org: Organization,
    onboarding: None,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    fault(mocks["payroll"], kind="timeout", delay_seconds=2.5, path_prefix="/v1/employees")
    event = hire(db_session, org)

    result = EventProcessor(db_session, connector_settings).process(event.id)  # read timeout 1 s

    assert result.outcome == "retrying"
    *_, payroll = jobs(db_session, event)
    assert (payroll.status, payroll.error_category) == (JobStatus.RETRYING, "timeout")
    assert payroll.attempt_history[0].error_code == "read_timeout"


def test_a_waiting_event_is_not_processed_before_it_is_due(
    db_session: Session,
    org: Organization,
    onboarding: None,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    fault(mocks["slack"], kind="status", status=503, path_prefix="/scim/v2/Users")
    event = hire(db_session, org)
    processor = EventProcessor(db_session, connector_settings)
    processor.process(event.id)

    duplicate = processor.process(event.id)  # an old message delivered again meanwhile

    assert duplicate.outcome == "skipped"
    slack, *_ = jobs(db_session, event)
    assert (slack.status, slack.attempts) == (JobStatus.RETRYING, 1)


def test_retry_log_lines_say_when_the_next_attempt_is(
    db_session: Session,
    org: Organization,
    onboarding: None,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="syncforge.engine")
    fault(mocks["slack"], kind="status", status=503, path_prefix="/scim/v2/Users")
    event = hire(db_session, org)

    EventProcessor(db_session, connector_settings).process(event.id)

    [job_line] = [r for r in caplog.records if r.getMessage() == "synchronization job finished"]
    assert (job_line.status, job_line.attempt) == ("retrying", 1)  # type: ignore[attr-defined]
    assert job_line.next_attempt_at is not None  # type: ignore[attr-defined]
    [finish] = [r for r in caplog.records if r.getMessage() == "event processing finished"]
    assert finish.outcome == "retrying"  # type: ignore[attr-defined]


# ---- the attempts API ----------------------------------------------------------------


def test_attempts_api_lists_the_retry_history(
    client: TestClient,
    db_session: Session,
    org: Organization,
    onboarding: None,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    fault(mocks["google_workspace"], kind="status", status=503, path_prefix="/admin")
    event = hire(db_session, org)
    processor = EventProcessor(db_session, connector_settings)
    processor.process(event.id)
    make_due(db_session, event)
    OutboxRelay(db_session, noop_publish, connector_settings).run_once()
    processor.process(event.id)
    viewer = create_user(db_session)
    add_member(db_session, viewer, org, OrganizationRole.VIEWER)
    headers = auth_headers(viewer)

    attempts = client.get(
        f"/api/v1/organizations/{org.id}/events/{event.id}/attempts", headers=headers
    )
    detail = client.get(f"/api/v1/organizations/{org.id}/events/{event.id}", headers=headers)

    assert attempts.status_code == 200
    rows = [(a["position"], a["attempt_number"], a["outcome"]) for a in attempts.json()]
    assert rows == [(1, 1, "succeeded"), (2, 1, "failed"), (2, 2, "succeeded"), (3, 1, "succeeded")]
    google_failure = attempts.json()[1]
    assert (google_failure["http_status"], google_failure["error_category"]) == (503, "server")
    assert google_failure["retryable"] is True and google_failure["next_attempt_at"]
    assert detail.json()["status"] == "completed"
    assert detail.json()["executions"][0]["jobs"][1]["attempts"] == 2


def test_attempts_of_another_organizations_event_are_invisible(
    client: TestClient, db_session: Session, org: Organization
) -> None:
    other = create_organization(db_session)
    outsider = create_user(db_session)
    add_member(db_session, outsider, other, OrganizationRole.ORG_ADMIN)
    event = hire(db_session, org)

    hidden = client.get(
        f"/api/v1/organizations/{other.id}/events/{event.id}/attempts",
        headers=auth_headers(outsider),
    )

    assert (hidden.status_code, hidden.json()["error"]["code"]) == (404, "event_not_found")
