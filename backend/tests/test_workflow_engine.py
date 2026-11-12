"""The workflow engine against the running mock services: onboarding, offboarding,
failures, duplicate delivery and crash recovery."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    Connector,
    ExecutionStatus,
    ExternalAccount,
    IntegrationEvent,
    IntegrationEventStatus,
    JobStatus,
    Organization,
    StepOperation,
    WorkflowExecution,
)
from app.schemas.employees import EmployeeCreate
from app.schemas.workflows import StepInput
from app.services.connectors import ConnectorService
from app.services.employees import EmployeeService
from app.services.workflows import WorkflowService
from app.workflows.engine import EventProcessor
from tests.factories import create_organization
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock

TYPES = ("slack", "google_workspace", "payroll")


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


def workflow(
    session: Session,
    org: Organization,
    trigger: str,
    steps: list[tuple[Connector, str]],
    *,
    name: str | None = None,
    active: bool = True,
) -> uuid.UUID:
    service = WorkflowService(session)
    created = service.create(
        org,
        name=name or trigger,
        description=None,
        trigger_event_type=trigger,
        steps=[StepInput(connector_id=c.id, operation=StepOperation(op)) for c, op in steps],
    )
    if active:
        service.set_active(org, created.id, active=True)
    return created.id


def hire(session: Session, org: Organization, number: str = "E-1001") -> IntegrationEvent:
    service = EmployeeService(session)
    service.create(
        org,
        EmployeeCreate(
            employee_number=number,
            first_name="Grace",
            last_name="Hopper",
            email=f"grace.{number.lower()}@acme.example",
            joining_date="2026-11-01",
        ),
    )
    return service.recorded_events[0]


def executions(session: Session, event: IntegrationEvent) -> list[WorkflowExecution]:
    return list(
        session.scalars(select(WorkflowExecution).where(WorkflowExecution.event_id == event.id))
    )


def mock_calls(mock: RunningMock, method: str, path_prefix: str) -> int:
    return sum(
        1
        for r in mock.state.requests
        if r["method"] == method and r["path"].startswith(path_prefix) and r["status"] < 400
    )


CREATE_PATHS = {
    "slack": ("POST", "/scim/v2/Users"),
    "google_workspace": ("POST", "/admin/directory/v1/users"),
    "payroll": ("POST", "/v1/employees"),
}


def test_onboarding_creates_accounts_in_every_application(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    workflow(db_session, org, "employee.created", [(apps[t], "create_user") for t in TYPES])
    event = hire(db_session, org)

    result = EventProcessor(db_session, connector_settings).process(event.id)

    assert (result.outcome, result.executions) == ("completed", 1)
    db_session.refresh(event)
    assert event.status is IntegrationEventStatus.COMPLETED
    assert (event.attempts, event.locked_until, event.last_error) == (1, None, None)
    [execution] = executions(db_session, event)
    assert execution.status is ExecutionStatus.SUCCEEDED and execution.workflow_version == 1
    assert [(j.position, j.status, j.attempts) for j in execution.jobs] == [
        (1, JobStatus.SUCCEEDED, 1),
        (2, JobStatus.SUCCEEDED, 1),
        (3, JobStatus.SUCCEEDED, 1),
    ]
    for job, connector_type in zip(execution.jobs, TYPES, strict=True):
        assert job.external_id in mocks[connector_type].state.users
    links = db_session.scalars(
        select(ExternalAccount).where(ExternalAccount.employee_id == event.employee_id)
    ).all()
    assert len(links) == 3


def test_offboarding_deactivates_the_accounts(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    workflow(db_session, org, "employee.created", [(apps[t], "create_user") for t in TYPES])
    workflow(db_session, org, "employee.terminated", [(apps[t], "deactivate_user") for t in TYPES])
    processor = EventProcessor(db_session, connector_settings)
    hired = hire(db_session, org)
    processor.process(hired.id)

    service = EmployeeService(db_session)
    service.terminate(org, hired.employee_id, termination_date=None)
    [terminated] = service.recorded_events
    result = processor.process(terminated.id)

    assert result.outcome == "completed"
    [execution] = executions(db_session, terminated)
    assert all(j.status is JobStatus.SUCCEEDED for j in execution.jobs)
    assert mocks["slack"].state.users[execution.jobs[0].external_id]["active"] is False
    assert mocks["google_workspace"].state.users[execution.jobs[1].external_id]["suspended"]
    assert mocks["payroll"].state.users[execution.jobs[2].external_id]["status"] == "inactive"


def test_events_without_an_active_workflow_complete_with_nothing_to_do(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    connector_settings: Settings,
) -> None:
    workflow(db_session, org, "employee.created", [(apps["slack"], "create_user")], active=False)
    workflow(db_session, org, "employee.terminated", [(apps["slack"], "deactivate_user")])
    event = hire(db_session, org)

    result = EventProcessor(db_session, connector_settings).process(event.id)

    assert (result.outcome, result.executions) == ("completed", 0)
    assert executions(db_session, event) == []


def test_a_failed_step_fails_the_execution_and_skips_the_rest(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    """A non-retryable failure (here 400: Google rejected the data) fails for good.
    Retryable failures are covered in test_retries.py."""
    from mockservices.faults import FaultSpec

    workflow(db_session, org, "employee.created", [(apps[t], "create_user") for t in TYPES])
    mocks["google_workspace"].state.faults.append(
        FaultSpec(kind="status", status=400, path_prefix="/admin")
    )
    event = hire(db_session, org)

    result = EventProcessor(db_session, connector_settings).process(event.id)

    assert result.outcome == "dead_letter"
    db_session.refresh(event)
    assert event.status is IntegrationEventStatus.DEAD_LETTER
    assert event.last_error == "1 of 1 workflow execution(s) failed."
    [execution] = executions(db_session, event)
    assert execution.status is ExecutionStatus.FAILED
    slack, google, payroll = execution.jobs
    assert slack.status is JobStatus.SUCCEEDED
    assert (google.status, google.error_category, google.attempts) == (
        JobStatus.FAILED,
        "validation",
        1,
    )
    assert "400" in google.error_message
    assert (payroll.status, payroll.attempts) == (JobStatus.SKIPPED, 0)
    assert mocks["payroll"].state.users == {}  # never called


def test_steps_that_do_not_apply_are_skipped_not_failed(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    connector_settings: Settings,
) -> None:
    # Offboarding an employee who never got a Slack account: nothing to deactivate.
    workflow(db_session, org, "employee.terminated", [(apps["slack"], "deactivate_user")])
    hired = hire(db_session, org)
    service = EmployeeService(db_session)
    service.terminate(org, hired.employee_id, termination_date=None)

    result = EventProcessor(db_session, connector_settings).process(service.recorded_events[0].id)

    assert result.outcome == "completed"
    [execution] = executions(db_session, service.recorded_events[0])
    [job] = execution.jobs
    assert job.status is JobStatus.SKIPPED
    assert job.error_message == "The employee has no account in this application."


def test_a_disconnected_connector_fails_its_step_as_configuration(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    connector_settings: Settings,
) -> None:
    workflow(db_session, org, "employee.created", [(apps["slack"], "create_user")])
    ConnectorService(db_session, connector_settings).disconnect(org, apps["slack"].id)
    event = hire(db_session, org)

    EventProcessor(db_session, connector_settings).process(event.id)

    [execution] = executions(db_session, event)
    assert (execution.jobs[0].status, execution.jobs[0].error_category) == (
        JobStatus.FAILED,
        "configuration",
    )


def test_duplicate_delivery_is_skipped_and_creates_nothing_twice(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    workflow(db_session, org, "employee.created", [(apps[t], "create_user") for t in TYPES])
    event = hire(db_session, org)
    processor = EventProcessor(db_session, connector_settings)

    first = processor.process(event.id)
    second = processor.process(event.id)  # the broker delivered the message again

    assert (first.outcome, second.outcome) == ("completed", "skipped")
    db_session.refresh(event)
    assert event.attempts == 1
    for connector_type in TYPES:
        assert mock_calls(mocks[connector_type], *CREATE_PATHS[connector_type]) == 1
    assert len(executions(db_session, event)) == 1


def test_an_event_owned_by_a_live_worker_is_not_claimed_twice(
    db_session: Session, org: Organization, connector_settings: Settings
) -> None:
    event = hire(db_session, org)
    event.status = IntegrationEventStatus.PROCESSING
    event.locked_until = datetime.now(UTC) + timedelta(minutes=5)  # lease still valid
    db_session.commit()

    result = EventProcessor(db_session, connector_settings).process(event.id)

    assert result.outcome == "skipped"


def test_a_crashed_worker_is_resumed_without_repeating_finished_work(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    """Simulate a worker that died right after Slack created the account, before the
    job was marked succeeded: the event is still `processing`, its lease has expired,
    Slack's job is `running`, the other two are `pending`."""
    workflow(db_session, org, "employee.created", [(apps[t], "create_user") for t in TYPES])
    event = hire(db_session, org)
    processor = EventProcessor(db_session, connector_settings)
    # Let a first run do the Slack step only, by making Google fail for good ...
    from mockservices.faults import FaultSpec

    mocks["google_workspace"].state.faults.append(
        FaultSpec(kind="status", status=400, path_prefix="/admin")
    )
    processor.process(event.id)
    # ... then rewind the database to the moment of the "crash": Slack's attempt still
    # open (no outcome), Google and payroll never attempted.
    [execution] = executions(db_session, event)
    slack, google, payroll = execution.jobs
    slack.status, slack.external_id = JobStatus.RUNNING, None
    slack.attempt_history[0].outcome = None
    slack.attempt_history[0].finished_at = None
    google.status, google.error_category, google.error_message = JobStatus.PENDING, None, None
    google.attempts = 0
    google.attempt_history.clear()
    payroll.status, payroll.error_message = JobStatus.PENDING, None
    execution.status = ExecutionStatus.RUNNING
    event.status = IntegrationEventStatus.PROCESSING
    event.locked_until = datetime.now(UTC) - timedelta(seconds=1)  # lease expired
    db_session.commit()

    result = processor.process(event.id)  # the relay re-dispatched it

    assert result.outcome == "completed"
    db_session.refresh(event)
    assert event.attempts == 2
    db_session.refresh(execution)
    assert [j.status for j in execution.jobs] == [JobStatus.SUCCEEDED] * 3
    # Slack's account was found through the stored link, not created a second time.
    assert mock_calls(mocks["slack"], *CREATE_PATHS["slack"]) == 1
    assert slack.external_id in mocks["slack"].state.users
    assert len(executions(db_session, event)) == 1
    # The attempt the dead worker left open is closed as interrupted.
    db_session.refresh(slack)
    assert [a.outcome.value for a in slack.attempt_history] == ["interrupted", "succeeded"]


def test_executions_keep_the_steps_they_ran_with(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    connector_settings: Settings,
) -> None:
    workflow_id = workflow(db_session, org, "employee.created", [(apps["slack"], "create_user")])
    event = hire(db_session, org)
    EventProcessor(db_session, connector_settings).process(event.id)

    WorkflowService(db_session).update(
        org,
        workflow_id,
        {"steps": [StepInput(connector_id=apps["payroll"].id, operation="create_user")]},
    )

    [execution] = executions(db_session, event)
    db_session.refresh(execution)
    assert execution.workflow_version == 1
    assert [j.connector_id for j in execution.jobs] == [apps["slack"].id]


def test_engine_logs_carry_ids_but_no_personal_data(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    connector_settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="syncforge.engine")
    workflow(db_session, org, "employee.created", [(apps["slack"], "create_user")])
    event = hire(db_session, org)

    EventProcessor(db_session, connector_settings).process(event.id)

    messages = [r.getMessage() for r in caplog.records if r.name == "syncforge.engine"]
    assert messages == [
        "event processing started",
        "synchronization job finished",
        "event processing finished",
    ]
    for record in caplog.records:
        assert getattr(record, "event_id", str(event.id)) == str(event.id)
        assert "grace" not in str(vars(record)).lower()


def test_relay_recovery_hands_a_crashed_workers_event_to_the_next_worker(
    db_session: Session,
    org: Organization,
    apps: dict[str, Connector],
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    """Relay and engine together: the relay must leave a re-dispatched event claimable.

    (Found in the live crash demo: re-dispatching used to renew the lease of the
    `processing` event, so the next worker saw a valid lease and skipped it.)
    """
    from app.events.relay import OutboxRelay

    workflow(db_session, org, "employee.created", [(apps["slack"], "create_user")])
    event = hire(db_session, org)
    published: list[str] = []
    relay = OutboxRelay(db_session, lambda event_id, _: published.append(event_id))
    relay.run_once()
    # A worker claimed the event and died: processing, lease expired.
    event.status = IntegrationEventStatus.PROCESSING
    event.attempts = 1
    event.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert relay.run_once().requeued == 1
    result = EventProcessor(db_session, connector_settings).process(event.id)

    assert result.outcome == "completed"
    db_session.refresh(event)
    assert (event.status, event.attempts) == (IntegrationEventStatus.COMPLETED, 2)
    assert published == [str(event.id), str(event.id)]
