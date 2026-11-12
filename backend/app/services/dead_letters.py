"""Dead-letter queue use cases: inspect entries and replay events.

Replay sends a dead-lettered event back through the normal pipeline:

1. Lock the entry and the event (SELECT ... FOR UPDATE), so two users clicking
   "Replay" at the same time cannot both replay it: the second one waits, then sees the
   entry already replayed and gets 409.
2. Reset only what failed. In each failed execution whose workflow is still active, the
   failed steps - and the steps skipped *because* of them (never attempted) - go back to
   `pending`. Steps that succeeded stay succeeded, so a replay never repeats finished
   work (no second Slack account). Each reset step gets a fresh retry budget
   (`attempts_at_last_replay`), while its attempt history and numbering are kept.
3. Put the event back to `pending` and write an outbox row - in the same transaction as
   the reset and as closing the entry (transactional outbox, as for new events). The
   relay publishes it and a worker processes it like any other event.

The entry itself is never edited beyond its status and who replayed it: the original
error stays as evidence. If the replay fails again, the engine opens a new entry.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models import (
    DeadLetterEvent,
    DeadLetterStatus,
    ExecutionStatus,
    IntegrationEvent,
    IntegrationEventStatus,
    JobStatus,
    Organization,
    OutboxEvent,
    User,
    WorkflowExecution,
)
from app.repositories.dead_letters import DeadLetterRepository

logger = logging.getLogger("syncforge.dead_letter")


class DeadLetterService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.entries = DeadLetterRepository(session)

    def get(self, organization: Organization, entry_id: uuid.UUID) -> DeadLetterEvent:
        entry = self.entries.get(organization.id, entry_id)
        if entry is None:
            raise NotFoundError("Dead-letter entry not found.", code="dead_letter_not_found")
        return entry

    def replay(
        self, organization: Organization, entry_id: uuid.UUID, actor: User
    ) -> DeadLetterEvent:
        entry = self.entries.get(organization.id, entry_id, for_update=True)
        if entry is None:
            raise NotFoundError("Dead-letter entry not found.", code="dead_letter_not_found")
        if entry.status is not DeadLetterStatus.OPEN:
            replayed_at = entry.replayed_at.isoformat() if entry.replayed_at else None
            self.session.rollback()
            raise ConflictError(
                "This entry has already been replayed.",
                code="already_replayed",
                details={"replayed_at": replayed_at},
            )
        event = self.entries.event(organization.id, entry.event_id, for_update=True)
        if event is None or event.status is not IntegrationEventStatus.DEAD_LETTER:
            self.session.rollback()  # cannot happen through the API; guards the invariant
            raise ConflictError(
                "The event is not in the dead-letter state.", code="event_not_dead_lettered"
            )

        replayable = [
            execution
            for execution, workflow in self.entries.failed_executions(organization.id, event.id)
            if workflow.is_active
        ]
        if not replayable:
            self.session.rollback()
            raise ConflictError(
                "None of the workflows that failed is active any more. Activate the "
                "workflow (after fixing its configuration) and replay again.",
                code="workflow_inactive",
            )

        reset_steps = sum(self._reset(execution) for execution in replayable)
        self._requeue(event)
        now = datetime.now(UTC)
        entry.status = DeadLetterStatus.REPLAYED
        entry.replayed_at = now
        entry.replayed_by_user_id = actor.id
        self.session.commit()
        logger.info(
            "dead-letter event replayed",
            extra={
                "dead_letter_id": str(entry.id),
                "event_id": str(event.id),
                "executions": len(replayable),
                "steps_reset": reset_steps,
                "replayed_by": str(actor.id),
            },
        )
        return entry

    @staticmethod
    def _reset(execution: WorkflowExecution) -> int:
        reset = 0
        for job in execution.jobs:
            never_attempted = job.status is JobStatus.SKIPPED and job.attempts == 0
            if job.status is JobStatus.FAILED or never_attempted:
                job.status = JobStatus.PENDING
                job.attempts_at_last_replay = job.attempts
                job.next_attempt_at = None
                job.error_category = None
                job.error_message = None
                job.started_at = None
                job.finished_at = None
                reset += 1
        execution.status = ExecutionStatus.RUNNING
        execution.finished_at = None
        return reset

    def _requeue(self, event: IntegrationEvent) -> None:
        event.status = IntegrationEventStatus.PENDING
        event.locked_until = None  # set by the relay when it publishes
        event.next_attempt_at = None
        event.completed_at = None
        event.last_error = None
        self.session.add(OutboxEvent(event_id=event.id))
