"""End to end through real Celery: outbox relay -> broker -> worker -> engine -> mocks.

The broker is Celery's in-memory transport (so the test needs no Redis server) and the
worker runs in a background thread. Everything else is real: the relay's publisher, the
task, the engine, the connectors and the mock services over HTTP.
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from celery.contrib.testing.worker import start_worker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.events.relay import OutboxRelay
from app.models import IntegrationEventStatus, JobStatus, StepOperation, WorkflowExecution
from app.schemas.employees import EmployeeCreate
from app.schemas.workflows import StepInput
from app.services.connectors import ConnectorService
from app.services.employees import EmployeeService
from app.services.workflows import WorkflowService
from app.workers import tasks
from app.workers.celery_app import celery_app
from tests.factories import create_organization
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock


@pytest.fixture
def worker(
    db_session: Session, connector_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[list[threading.Event]]:
    """A running Celery worker whose tasks use the test's session and mock settings.

    Yields a list; append a threading.Event to it before publishing, and the worker sets
    the oldest one when it finishes a task. (The test thread waits on the event instead
    of touching the session while the worker uses it.)
    """
    finished: list[threading.Event] = []

    @contextmanager
    def test_session() -> Iterator[Session]:
        try:
            yield db_session
        finally:
            finished.pop(0).set()

    monkeypatch.setattr(tasks, "session_factory", test_session)
    monkeypatch.setattr("app.workflows.engine.get_settings", lambda: connector_settings)
    original = {
        "broker_url": celery_app.conf.broker_url,
        "broker_transport_options": celery_app.conf.broker_transport_options,
    }
    celery_app.conf.update(broker_url="memory://", broker_transport_options={})
    try:
        with start_worker(celery_app, pool="solo", perform_ping_check=False, shutdown_timeout=10):
            yield finished
    finally:
        celery_app.conf.update(original)


def deliver(finished: list[threading.Event], publish: Callable[[], object]) -> None:
    done = threading.Event()
    finished.append(done)
    publish()
    assert done.wait(timeout=20), "the worker did not process the message in time"


def test_relay_to_worker_onboarding_and_duplicate_delivery(
    db_session: Session,
    connector_settings: Settings,
    mocks: dict[str, RunningMock],
    worker: list[threading.Event],
) -> None:
    org = create_organization(db_session)
    connectors = ConnectorService(db_session, connector_settings)
    steps = [
        StepInput(
            connector_id=connectors.create(
                org, connector_type=t, name=t, config={}, credentials=MOCK_CREDENTIALS[t]
            ).id,
            operation=StepOperation.CREATE_USER,
        )
        for t in ("slack", "google_workspace", "payroll")
    ]
    workflows = WorkflowService(db_session)
    onboarding = workflows.create(
        org, name="Onboarding", description=None, trigger_event_type="employee.created", steps=steps
    )
    workflows.set_active(org, onboarding.id, active=True)
    employees = EmployeeService(db_session)
    employees.create(
        org,
        EmployeeCreate(
            employee_number="E-7",
            first_name="Ada",
            last_name="Lovelace",
            email="ada@acme.example",
            joining_date="2026-11-01",
        ),
    )
    [event] = employees.recorded_events

    # The relay publishes the outbox row through the real Celery publisher.
    deliver(worker, lambda: OutboxRelay(db_session, tasks.publish_event).publish_pending())

    db_session.refresh(event)
    assert event.status is IntegrationEventStatus.COMPLETED
    [execution] = db_session.scalars(
        select(WorkflowExecution).where(WorkflowExecution.event_id == event.id)
    ).all()
    assert [j.status for j in execution.jobs] == [JobStatus.SUCCEEDED] * 3
    assert all(len(mock.state.users) == 1 for mock in mocks.values())

    # The broker delivers the same message again: the worker skips it.
    deliver(worker, lambda: tasks.publish_event(str(event.id), event.correlation_id))

    db_session.refresh(event)
    assert (event.status, event.attempts) == (IntegrationEventStatus.COMPLETED, 1)
    assert all(len(mock.state.users) == 1 for mock in mocks.values())
