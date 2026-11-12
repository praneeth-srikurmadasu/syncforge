"""Circuit breaker, per-connector rate limits and the operation deadline."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.errors import ConnectorError, ErrorCategory
from app.core.config import Settings
from app.events.relay import OutboxRelay
from app.models import (
    CircuitState,
    Connector,
    ConnectorCircuit,
    ConnectorRateWindow,
    JobStatus,
    Organization,
    OrganizationRole,
    StepOperation,
    SynchronizationAttempt,
)
from app.reliability import rate_limit as rate_limit_module
from app.reliability.circuit_breaker import CircuitBreaker
from app.reliability.rate_limit import RateLimiter
from app.schemas.workflows import StepInput
from app.services.connectors import ConnectorService
from app.services.workflows import WorkflowService
from app.workflows.engine import EventProcessor
from tests.factories import add_member, auth_headers, create_organization, create_user
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock
from tests.test_connector_adapters import GRACE, build
from tests.test_retries import fault, hire, jobs, make_due, noop_publish

TYPES = ("slack", "google_workspace", "payroll")


@pytest.fixture
def settings(connector_settings: Settings) -> Settings:
    return connector_settings.model_copy(
        update={"circuit_failure_threshold": 2, "circuit_open_seconds": 30}
    )


@pytest.fixture
def org(db_session: Session) -> Organization:
    return create_organization(db_session)


@pytest.fixture
def slack(
    db_session: Session, org: Organization, mocks: dict[str, RunningMock], settings: Settings
) -> Connector:
    return ConnectorService(db_session, settings).create(
        org, connector_type="slack", name="Slack", config={}, credentials=MOCK_CREDENTIALS["slack"]
    )


def outage() -> ConnectorError:
    return ConnectorError(ErrorCategory.SERVER, "Service Unavailable", "http_503", 503)


def circuit(session: Session, connector: Connector) -> ConnectorCircuit:
    return session.scalars(
        select(ConnectorCircuit)
        .where(ConnectorCircuit.connector_id == connector.id)
        .execution_options(populate_existing=True)
    ).one()


# ---- the state machine -------------------------------------------------------------------


def test_consecutive_outage_failures_open_the_circuit(
    db_session: Session, slack: Connector, settings: Settings
) -> None:
    breaker = CircuitBreaker(db_session, settings)
    breaker.before_call(slack)
    breaker.record(slack, outage())
    assert circuit(db_session, slack).state is CircuitState.CLOSED  # 1 of 2

    breaker.record(slack, outage())

    state = circuit(db_session, slack)
    assert (state.state, state.consecutive_failures) == (CircuitState.OPEN, 2)
    with pytest.raises(ConnectorError) as raised:
        breaker.before_call(slack)
    assert (raised.value.category, raised.value.retryable) == (ErrorCategory.CIRCUIT_OPEN, True)
    assert 25 <= raised.value.retry_after <= 30


@pytest.mark.parametrize(
    "answer",
    [
        None,
        ConnectorError(ErrorCategory.VALIDATION, "bad", "http_400", 400),
        ConnectorError(ErrorCategory.AUTHENTICATION, "no", "http_401", 401),
        ConnectorError(ErrorCategory.RATE_LIMITED, "slow down", "http_429", 429),
    ],
)
def test_any_real_answer_resets_the_count(
    db_session: Session, slack: Connector, settings: Settings, answer: ConnectorError | None
) -> None:
    breaker = CircuitBreaker(db_session, settings)
    breaker.record(slack, outage())

    breaker.record(slack, answer)  # the application answered: it is reachable
    breaker.record(slack, outage())

    state = circuit(db_session, slack)
    assert (state.state, state.consecutive_failures) == (CircuitState.CLOSED, 1)


def open_circuit(session: Session, connector: Connector, settings: Settings) -> CircuitBreaker:
    breaker = CircuitBreaker(session, settings)
    for _ in range(settings.circuit_failure_threshold):
        breaker.record(connector, outage())
    return breaker


def expire_open_period(session: Session, connector: Connector) -> None:
    state = circuit(session, connector)
    state.open_until = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()


def test_after_the_open_period_one_trial_call_is_let_through(
    db_session: Session, slack: Connector, settings: Settings
) -> None:
    breaker = open_circuit(db_session, slack, settings)
    expire_open_period(db_session, slack)

    breaker.before_call(slack)  # the trial
    assert circuit(db_session, slack).state is CircuitState.HALF_OPEN
    with pytest.raises(ConnectorError):
        breaker.before_call(slack)  # everyone else still waits

    breaker.record(slack, None)  # the trial succeeded
    state = circuit(db_session, slack)
    assert (state.state, state.consecutive_failures, state.open_until) == (
        CircuitState.CLOSED,
        0,
        None,
    )
    breaker.before_call(slack)  # calls flow again


def test_a_failed_trial_opens_the_circuit_again(
    db_session: Session, slack: Connector, settings: Settings
) -> None:
    breaker = open_circuit(db_session, slack, settings)
    expire_open_period(db_session, slack)
    breaker.before_call(slack)

    breaker.record(slack, outage())

    state = circuit(db_session, slack)
    assert state.state is CircuitState.OPEN
    assert state.open_until > datetime.now(UTC) + timedelta(seconds=25)


def test_an_abandoned_trial_is_replaced(
    db_session: Session, slack: Connector, settings: Settings
) -> None:
    breaker = open_circuit(db_session, slack, settings)
    expire_open_period(db_session, slack)
    breaker.before_call(slack)
    state = circuit(db_session, slack)
    state.trial_started_at = datetime.now(UTC) - timedelta(hours=1)  # its worker died
    db_session.commit()

    breaker.before_call(slack)  # allowed: becomes the new trial

    assert circuit(db_session, slack).trial_started_at > datetime.now(UTC) - timedelta(minutes=1)


# ---- the breaker in the engine -----------------------------------------------------------


@pytest.fixture
def onboarding(
    db_session: Session, org: Organization, mocks: dict[str, RunningMock], settings: Settings
) -> dict[str, Connector]:
    service = ConnectorService(db_session, settings)
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


def google_calls(mocks: dict[str, RunningMock]) -> int:
    return sum(
        1
        for r in mocks["google_workspace"].state.requests
        if r["method"] == "POST" and r["path"].endswith("/users")
    )


def test_an_open_circuit_stops_calls_from_every_job(
    db_session: Session,
    org: Organization,
    onboarding: dict[str, Connector],
    mocks: dict[str, RunningMock],
    settings: Settings,
) -> None:
    fault(mocks["google_workspace"], kind="status", status=503, count=100, path_prefix="/admin")
    first = hire(db_session, org)
    processor = EventProcessor(db_session, settings)
    relay = OutboxRelay(db_session, noop_publish, settings)

    processor.process(first.id)  # Google attempt 1: 503
    make_due(db_session, first)
    relay.run_once()
    processor.process(first.id)  # attempt 2: 503 -> the circuit opens
    assert circuit(db_session, onboarding["google_workspace"]).state is CircuitState.OPEN
    assert google_calls(mocks) == 2

    make_due(db_session, first)
    relay.run_once()
    processor.process(first.id)  # attempt 3: refused without a call
    second = hire(db_session, org)
    processor.process(second.id)  # another employee: refused too

    assert google_calls(mocks) == 2  # Google was left alone
    _, google, _ = jobs(db_session, first)
    refused = google.attempt_history[-1]
    assert (refused.error_category, refused.http_status, refused.retryable) == (
        "circuit_open",
        None,
        True,
    )
    open_until = circuit(db_session, onboarding["google_workspace"]).open_until
    assert google.status is JobStatus.RETRYING
    assert google.next_attempt_at >= open_until  # waits until a trial is possible
    _, other_google, _ = jobs(db_session, second)
    assert other_google.error_category == "circuit_open"


def test_a_successful_connection_test_closes_the_circuit(
    client: TestClient,
    db_session: Session,
    org: Organization,
    slack: Connector,
    settings: Settings,
) -> None:
    open_circuit(db_session, slack, settings)
    user = create_user(db_session)
    add_member(db_session, user, org, OrganizationRole.INTEGRATION_MANAGER)
    url = f"/api/v1/organizations/{org.id}/connectors/{slack.id}"

    shown = client.get(url, headers=auth_headers(user)).json()["circuit"]
    assert (shown["state"], shown["consecutive_failures"]) == ("open", 2)
    assert shown["open_until"] is not None

    ConnectorService(db_session, settings).test(org, slack.id)

    assert circuit(db_session, slack).state is CircuitState.CLOSED
    assert client.get(url, headers=auth_headers(user)).json()["circuit"]["state"] == "closed"


# ---- rate limits -------------------------------------------------------------------------


def test_the_rate_limiter_counts_calls_per_minute(
    db_session: Session, org: Organization, mocks: dict[str, RunningMock], settings: Settings
) -> None:
    connector = ConnectorService(db_session, settings).create(
        org,
        connector_type="slack",
        name="Slack",
        config={"rate_limit_per_minute": 2},
        credentials=MOCK_CREDENTIALS["slack"],
    )
    limiter = RateLimiter(db_session)
    now = datetime(2026, 11, 12, 10, 0, 45, tzinfo=UTC)

    assert limiter.acquire(connector, now=now) is None
    assert limiter.acquire(connector, now=now) is None
    assert limiter.acquire(connector, now=now) == 15  # seconds left in this minute
    assert limiter.acquire(connector, now=now + timedelta(seconds=20)) is None  # next minute


def test_connectors_without_a_limit_are_not_counted(db_session: Session, slack: Connector) -> None:
    assert RateLimiter(db_session).acquire(slack) is None
    assert db_session.scalars(select(ConnectorRateWindow)).all() == []


def test_jobs_over_the_limit_wait_without_using_an_attempt(
    db_session: Session,
    org: Organization,
    onboarding: dict[str, Connector],
    mocks: dict[str, RunningMock],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slack = onboarding["slack"]
    slack.config = {**slack.config, "rate_limit_per_minute": 1}
    db_session.commit()
    clock = {"now": datetime(2026, 11, 12, 10, 0, 30, tzinfo=UTC)}
    real_acquire = RateLimiter.acquire
    monkeypatch.setattr(
        rate_limit_module.RateLimiter,
        "acquire",
        lambda self, connector, now=None: real_acquire(self, connector, now=clock["now"]),
    )
    processor = EventProcessor(db_session, settings)
    first, second = hire(db_session, org), hire(db_session, org)

    assert processor.process(first.id).outcome == "completed"
    assert processor.process(second.id).outcome == "retrying"

    slack_job, google_job, _ = jobs(db_session, second)
    assert (slack_job.status, slack_job.attempts, slack_job.error_category) == (
        JobStatus.RETRYING,
        0,  # no attempt used
        "throttled",
    )
    wait = (slack_job.next_attempt_at - datetime.now(UTC)).total_seconds()
    assert 29 <= wait <= 31.5  # the rest of the minute, plus up to 1 s of spread
    assert (
        db_session.scalars(
            select(SynchronizationAttempt).where(SynchronizationAttempt.job_id == slack_job.id)
        ).all()
        == []
    )
    assert google_job.status is JobStatus.PENDING
    assert len(mocks["slack"].state.users) == 1

    clock["now"] += timedelta(minutes=1)  # the next minute
    make_due(db_session, second)
    OutboxRelay(db_session, noop_publish, settings).run_once()
    assert processor.process(second.id).outcome == "completed"
    assert len(mocks["slack"].state.users) == 2


def test_an_invalid_rate_limit_is_rejected(
    client: TestClient, db_session: Session, org: Organization
) -> None:
    user = create_user(db_session)
    add_member(db_session, user, org, OrganizationRole.ORG_ADMIN)

    response = client.post(
        f"/api/v1/organizations/{org.id}/connectors",
        headers=auth_headers(user),
        json={
            "connector_type": "slack",
            "name": "Slack",
            "config": {"rate_limit_per_minute": 0},
            "credentials": MOCK_CREDENTIALS["slack"],
        },
    )

    assert response.status_code == 422


# ---- operation deadline ------------------------------------------------------------------


def test_one_operation_cannot_exceed_its_deadline_across_requests(
    mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    """Slack's deactivate is two requests (DELETE, then GET). Each stays within the 1 s
    read timeout, but together they exceed the 1 s operation limit."""
    settings = connector_settings.model_copy(update={"connector_operation_timeout_seconds": 1.0})
    created = build("slack", connector_settings).create_user(GRACE)
    fault(mocks["slack"], kind="timeout", delay_seconds=0.6, count=2, path_prefix="/scim/v2/Users/")

    with pytest.raises(ConnectorError) as raised:
        build("slack", settings).deactivate_user(created.external_id)

    assert (raised.value.category, raised.value.code) == (
        ErrorCategory.TIMEOUT,
        "operation_timeout",
    )
    assert raised.value.retryable is True


def test_requests_after_the_deadline_are_not_sent(
    mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    connector = build("slack", connector_settings)
    connector.http.deadline = 0.0  # long past
    sent_before = len(mocks["slack"].state.requests)

    with pytest.raises(ConnectorError) as raised:
        connector.get_user("U123")

    assert raised.value.code == "operation_timeout"
    assert len(mocks["slack"].state.requests) == sent_before


def test_circuit_rows_belong_to_the_connector(
    db_session: Session, slack: Connector, settings: Settings
) -> None:
    open_circuit(db_session, slack, settings)

    db_session.delete(slack)
    db_session.commit()

    assert db_session.scalars(select(ConnectorCircuit)).all() == []
