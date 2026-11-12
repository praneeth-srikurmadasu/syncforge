"""Celery tasks. Thin wrappers: open a session, run the engine, close the session."""

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.request_context import reset_request_id, set_request_id
from app.workers.celery_app import PROCESS_EVENT_TASK, celery_app
from app.workflows.engine import EventProcessor

# Replaced in tests to run tasks inside the test's transaction.
session_factory: Callable[[], AbstractContextManager[Session]] = SessionLocal


@celery_app.task(name=PROCESS_EVENT_TASK)
def process_event(event_id: str, correlation_id: str | None = None) -> str:
    """Process one integration event. Safe to run more than once for the same event."""
    # The correlation ID becomes the log context, so every worker log line carries the
    # request ID of the API call that caused the event.
    token = set_request_id(correlation_id)
    try:
        with session_factory() as session:
            return EventProcessor(session).process(uuid.UUID(event_id)).outcome
    finally:
        reset_request_id(token)


def publish_event(event_id: str, correlation_id: str | None) -> None:
    """The relay's publisher: put 'process this event' on the queue."""
    process_event.apply_async(args=[event_id, correlation_id])
