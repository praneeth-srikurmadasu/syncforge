"""Dead-lettering: park an event whose processing failed for good.

Called by the engine (inside its final transaction) when an event ends with at least one
failed execution. Replaying an entry is a user action and lives in
app/services/dead_letters.py.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DeadLetterEvent,
    DeadLetterReason,
    DeadLetterStatus,
    ExecutionStatus,
    IntegrationEvent,
    JobStatus,
    WorkflowExecution,
)

logger = logging.getLogger("syncforge.dead_letter")


def dead_letter(
    session: Session,
    event: IntegrationEvent,
    failed_executions: list[WorkflowExecution],
) -> DeadLetterEvent | None:
    """Stage the dead-letter entry for `event` (the caller commits).

    Returns None if the event already has an open entry: a worker whose lease raced out
    can finish the same event twice, and the partial unique index would refuse a second
    open entry anyway.
    """
    existing = session.scalar(
        select(DeadLetterEvent).where(
            DeadLetterEvent.event_id == event.id,
            DeadLetterEvent.status == DeadLetterStatus.OPEN,
        )
    )
    if existing is not None:
        return None

    failed_jobs = [
        job
        for execution in failed_executions
        if execution.status is ExecutionStatus.FAILED
        for job in execution.jobs
        if job.status is JobStatus.FAILED
    ]
    first = failed_jobs[0] if failed_jobs else None
    last_attempt = first.attempt_history[-1] if first and first.attempt_history else None
    attempts = first.attempts - first.attempts_at_last_replay if first else 0
    # A retryable error only fails a job once the retry budget is used up.
    exhausted = bool(last_attempt and last_attempt.retryable)

    entry = DeadLetterEvent(
        organization_id=event.organization_id,
        event_id=event.id,
        reason=DeadLetterReason.RETRIES_EXHAUSTED if exhausted else DeadLetterReason.NON_RETRYABLE,
        job_id=first.id if first else None,
        connector_id=first.connector_id if first else None,
        operation=first.operation if first else None,
        error_category=first.error_category if first else None,
        error_code=last_attempt.error_code if last_attempt else None,
        http_status=last_attempt.http_status if last_attempt else None,
        error_message=first.error_message if first else event.last_error,
        attempts=attempts,
        failed_steps=max(len(failed_jobs), 1),
        dead_lettered_at=datetime.now(UTC),
    )
    session.add(entry)
    session.flush()
    logger.warning(
        "event dead-lettered",
        extra={
            "event_id": str(event.id),
            "dead_letter_id": str(entry.id),
            "reason": entry.reason.value,
            "connector_id": str(entry.connector_id) if entry.connector_id else None,
            "operation": entry.operation,
            "error_category": entry.error_category,
            "attempts": entry.attempts,
        },
    )
    return entry
