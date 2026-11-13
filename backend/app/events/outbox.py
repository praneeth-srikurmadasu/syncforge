"""Write lifecycle events into the transactional outbox.

`record_events` adds one `integration_events` row and one `outbox_events` row per
lifecycle event to the caller's session. It never commits: the caller commits the
employee change, the events and the outbox rows together, in one transaction. If that
transaction rolls back, none of them exist; if it commits, all of them do. That is the
whole point of the pattern - there is no window in which the employee changed but the
event was lost, or an event was published for a change that never happened.

Publishing to the broker happens later and separately (the outbox relay, docs/architecture.md).
"""

from sqlalchemy.orm import Session

from app.core.request_context import get_request_id
from app.events.lifecycle import LifecycleEvent
from app.models import IntegrationEvent, OutboxEvent


def record_events(session: Session, events: list[LifecycleEvent]) -> list[IntegrationEvent]:
    """Stage events and their outbox rows in `session` (flushed, not committed)."""
    correlation_id = get_request_id()
    records: list[IntegrationEvent] = []
    for event in events:
        record = IntegrationEvent(
            organization_id=event.organization_id,
            event_type=event.type.value,
            employee_id=event.employee_id,
            payload=event.payload(),
            correlation_id=correlation_id,
        )
        session.add(record)
        records.append(record)
    if records:
        session.flush()  # assigns event IDs for the outbox rows
        session.add_all(OutboxEvent(event_id=record.id) for record in records)
        session.flush()
    return records
