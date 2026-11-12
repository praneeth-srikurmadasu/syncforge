"""The outbox relay: publishes in order, survives broker outages, and re-dispatches
events whose worker lease expired."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.events.relay import OutboxRelay
from app.models import IntegrationEvent, IntegrationEventStatus, OutboxEvent
from app.services.employees import EmployeeService
from tests.factories import create_employee, create_organization


class FakeBroker:
    """Records published event IDs; can be switched off to simulate an outage."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str | None]] = []
        self.down = False

    def __call__(self, event_id: str, correlation_id: str | None) -> None:
        if self.down:
            raise ConnectionError("Error 111 connecting to localhost:6379. Connection refused.")
        self.published.append((event_id, correlation_id))


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker()


def make_events(session: Session, count: int) -> list[IntegrationEvent]:
    org = create_organization(session)
    employee = create_employee(session, org)
    service = EmployeeService(session)
    records = []
    for i in range(count):
        service.update(org, employee.id, {"location": f"City {i}"})
        records += service.recorded_events
    return records


def outbox(session: Session) -> list[OutboxEvent]:
    return list(session.scalars(select(OutboxEvent).order_by(OutboxEvent.id)))


def test_publishes_unpublished_rows_in_order_and_marks_them(
    db_session: Session, broker: FakeBroker
) -> None:
    events = make_events(db_session, 3)

    result = OutboxRelay(db_session, broker).run_once()

    assert (result.published, result.failed) == (3, False)
    assert [event_id for event_id, _ in broker.published] == [str(e.id) for e in events]
    assert all(row.published_at is not None for row in outbox(db_session))
    # A published event is "queued" for one lease period before recovery looks at it.
    db_session.refresh(events[0])
    assert events[0].locked_until > datetime.now(UTC)

    assert OutboxRelay(db_session, broker).run_once().published == 0  # nothing left


def test_respects_the_batch_size(db_session: Session, broker: FakeBroker) -> None:
    make_events(db_session, 3)
    settings = get_settings().model_copy(update={"outbox_batch_size": 2})

    assert OutboxRelay(db_session, broker, settings).run_once().published == 2
    assert OutboxRelay(db_session, broker, settings).run_once().published == 1


def test_a_broker_outage_keeps_rows_for_the_next_poll(
    db_session: Session, broker: FakeBroker
) -> None:
    events = make_events(db_session, 2)
    broker.down = True

    result = OutboxRelay(db_session, broker).run_once()

    assert (result.published, result.failed) == (0, True)
    first, second = outbox(db_session)
    assert first.published_at is None and first.publish_attempts == 1
    assert "Connection refused" in first.last_error
    assert second.publish_attempts == 0  # the round stopped at the first failure

    broker.down = False
    assert OutboxRelay(db_session, broker).run_once().published == 2
    assert [e for e, _ in broker.published] == [str(e.id) for e in events]
    assert outbox(db_session)[0].last_error is None


def test_events_with_an_expired_lease_are_re_dispatched(
    db_session: Session, broker: FakeBroker
) -> None:
    crashed, lost, healthy, finished = make_events(db_session, 4)
    OutboxRelay(db_session, broker).run_once()
    broker.published.clear()
    past = datetime.now(UTC) - timedelta(seconds=1)
    crashed.status, crashed.locked_until = IntegrationEventStatus.PROCESSING, past  # worker died
    lost.locked_until = past  # still pending long after publication: message lost
    finished.status, finished.locked_until = IntegrationEventStatus.COMPLETED, past
    db_session.commit()

    result = OutboxRelay(db_session, broker).run_once()

    assert result.requeued == 2
    assert {e for e, _ in broker.published} == {str(crashed.id), str(lost.id)}
    db_session.refresh(crashed)
    # The crashed worker's event is back to pending, so the next worker can claim it.
    assert crashed.status is IntegrationEventStatus.PENDING
    assert crashed.locked_until > datetime.now(UTC)  # not re-sent again on the next poll
    assert OutboxRelay(db_session, broker).run_once().requeued == 0
    assert healthy.status is IntegrationEventStatus.PENDING


def test_the_correlation_id_travels_with_the_message(
    db_session: Session, broker: FakeBroker
) -> None:
    from app.core.request_context import reset_request_id, set_request_id

    token = set_request_id("req-relay-42")
    try:
        make_events(db_session, 1)
    finally:
        reset_request_id(token)

    OutboxRelay(db_session, broker).run_once()

    assert broker.published[0][1] == "req-relay-42"
