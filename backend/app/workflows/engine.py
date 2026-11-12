"""The workflow engine: process one integration event.

Delivery is at-least-once (a message can arrive twice; a worker can die halfway), so
processing is built to be safe to repeat:

1. **Claim.** One atomic UPDATE moves the event to `processing` and sets a lease
   (`locked_until`). It succeeds only if the event is `pending`, or `processing` with an
   expired lease (its worker died). A duplicate delivery of an event another worker owns,
   or of a finished event, claims nothing and is skipped.
2. **Plan.** For every *active* workflow whose trigger matches, get or create the
   execution for (event, workflow) - a unique constraint makes it exactly one - and copy
   the workflow's steps into synchronization jobs.
3. **Run.** Jobs run in order. A job that already succeeded is skipped, so a resumed
   execution never repeats finished work. The lease is renewed before each job, and no
   database lock is held during the external call.
4. **Finish.** The event becomes `completed` if every execution succeeded (or nothing
   matched), otherwise `failed`.

Each connector call goes through `ConnectorService.run_operation`, which records the
external account link in its own commit. If a worker dies after the external call but
before the job is marked succeeded, the re-run finds the link and treats `create_user`
as already done instead of creating a second account.

What this module does NOT do yet (Phase 6): retry failed jobs with backoff, dead-letter
events, idempotency keys towards the external API, circuit breaking. A failed job here
fails its execution, and later steps are skipped.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, BadGatewayError
from app.models import (
    ExecutionStatus,
    IntegrationEvent,
    IntegrationEventStatus,
    JobStatus,
    Organization,
    SynchronizationJob,
    Workflow,
    WorkflowExecution,
)
from app.services.connectors import ConnectorService

logger = logging.getLogger("syncforge.engine")

# ConnectorService precondition codes that mean "nothing to do" rather than "failed".
_SKIP_CODES = {
    "not_linked": "The employee has no account in this application.",
    "employee_terminated": "Accounts are not created for terminated employees.",
}


@dataclass(frozen=True)
class ProcessResult:
    event_id: uuid.UUID
    outcome: str  # "completed", "failed", or "skipped" (not claimable)
    executions: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


class EventProcessor:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    # ---- public --------------------------------------------------------------------

    def process(self, event_id: uuid.UUID) -> ProcessResult:
        event = self._claim(event_id)
        if event is None:
            logger.info("event not claimable, skipped", extra={"event_id": str(event_id)})
            return ProcessResult(event_id, "skipped")

        log = {"event_id": str(event.id), "event_type": event.event_type}
        logger.info("event processing started", extra={**log, "attempt": event.attempts})
        organization = self.session.get(Organization, event.organization_id)
        executions = [self._plan(event, workflow) for workflow in self._workflows(event)]
        for execution in executions:
            if execution.status is ExecutionStatus.RUNNING:
                self._run(event, organization, execution)  # type: ignore[arg-type]

        failed = [e for e in executions if e.status is ExecutionStatus.FAILED]
        event.status = IntegrationEventStatus.FAILED if failed else IntegrationEventStatus.COMPLETED
        event.completed_at = _now()
        event.locked_until = None
        event.last_error = (
            f"{len(failed)} of {len(executions)} workflow execution(s) failed." if failed else None
        )
        self.session.commit()
        outcome = event.status.value
        logger.info(
            "event processing finished",
            extra={**log, "outcome": outcome, "executions": len(executions)},
        )
        return ProcessResult(event.id, outcome, len(executions))

    # ---- claim -----------------------------------------------------------------------

    def _claim(self, event_id: uuid.UUID) -> IntegrationEvent | None:
        now = _now()
        claimed = self.session.execute(
            update(IntegrationEvent)
            .where(
                IntegrationEvent.id == event_id,
                or_(
                    IntegrationEvent.status == IntegrationEventStatus.PENDING,
                    (IntegrationEvent.status == IntegrationEventStatus.PROCESSING)
                    & (IntegrationEvent.locked_until < now),
                ),
            )
            .values(
                status=IntegrationEventStatus.PROCESSING,
                locked_until=now + timedelta(seconds=self.settings.worker_lease_seconds),
                attempts=IntegrationEvent.attempts + 1,
                started_at=now,
            )
            .returning(IntegrationEvent.id)
        ).scalar()
        self.session.commit()
        if claimed is None:
            return None
        return self.session.scalar(
            select(IntegrationEvent)
            .where(IntegrationEvent.id == event_id)
            .execution_options(populate_existing=True)
        )

    def _renew_lease(self, event: IntegrationEvent) -> None:
        event.locked_until = _now() + timedelta(seconds=self.settings.worker_lease_seconds)

    # ---- plan --------------------------------------------------------------------------

    def _workflows(self, event: IntegrationEvent) -> list[Workflow]:
        return list(
            self.session.scalars(
                select(Workflow)
                .where(
                    Workflow.organization_id == event.organization_id,
                    Workflow.trigger_event_type == event.event_type,
                    Workflow.is_active.is_(True),
                )
                .order_by(Workflow.name, Workflow.id)
            )
        )

    def _plan(self, event: IntegrationEvent, workflow: Workflow) -> WorkflowExecution:
        existing = self._execution(event.id, workflow.id)
        if existing is not None:
            return existing  # redelivery or crash recovery: resume, never duplicate
        execution = WorkflowExecution(
            organization_id=event.organization_id,
            event_id=event.id,
            workflow_id=workflow.id,
            workflow_version=workflow.version,
            started_at=_now(),
        )
        execution.jobs = [
            SynchronizationJob(
                organization_id=event.organization_id,
                position=step.position,
                connector_id=step.connector_id,
                operation=step.operation,
                employee_id=event.employee_id,
            )
            for step in workflow.steps
        ]
        try:
            self.session.add(execution)
            self.session.commit()
        except IntegrityError:  # another worker planned it first (lease raced out)
            self.session.rollback()
            return self._execution(event.id, workflow.id)  # type: ignore[return-value]
        return execution

    def _execution(self, event_id: uuid.UUID, workflow_id: uuid.UUID) -> WorkflowExecution | None:
        return self.session.scalar(
            select(WorkflowExecution).where(
                WorkflowExecution.event_id == event_id,
                WorkflowExecution.workflow_id == workflow_id,
            )
        )

    # ---- run -------------------------------------------------------------------------

    def _run(
        self, event: IntegrationEvent, organization: Organization, execution: WorkflowExecution
    ) -> None:
        log = {
            "event_id": str(event.id),
            "execution_id": str(execution.id),
            "workflow_id": str(execution.workflow_id),
        }
        failed = False
        for job in execution.jobs:
            if job.status in (JobStatus.SUCCEEDED, JobStatus.SKIPPED):
                continue
            if job.status is JobStatus.FAILED:  # recorded before a crash: still final
                failed = True
                continue
            if failed:
                job.status = JobStatus.SKIPPED
                job.error_message = "Not attempted: an earlier step failed."
                continue
            self._renew_lease(event)
            job.status = JobStatus.RUNNING
            job.attempts += 1
            job.started_at = _now()
            self.session.commit()  # visible as running; no lock held during the call

            self._execute(organization, job)
            self.session.commit()
            logger.info(
                "synchronization job finished",
                extra={
                    **log,
                    "position": job.position,
                    "operation": job.operation,
                    "connector_id": str(job.connector_id),
                    "status": job.status.value,
                    "error_category": job.error_category,
                },
            )
            failed = job.status is JobStatus.FAILED

        execution.status = ExecutionStatus.FAILED if failed else ExecutionStatus.SUCCEEDED
        execution.finished_at = _now()
        self.session.commit()

    def _execute(self, organization: Organization, job: SynchronizationJob) -> None:
        service = ConnectorService(self.session, self.settings)
        job.error_category = None
        job.error_message = None
        try:
            result = service.run_operation(
                organization,
                job.connector_id,
                operation=job.operation,
                employee_id=job.employee_id,
            )
        except BadGatewayError as error:  # the external application failed
            details: dict[str, Any] = error.details or {}
            self._finish(job, JobStatus.FAILED, category=details.get("category"), message=error)
        except AppError as error:
            if error.code == "already_linked" and job.operation == "create_user":
                # Done earlier (e.g. by a run that crashed before recording success).
                external_id = (error.details or {}).get("external_id")
                self._finish(job, JobStatus.SUCCEEDED, external_id=external_id)
            elif error.code in _SKIP_CODES:
                self._finish(job, JobStatus.SKIPPED, message=_SKIP_CODES[error.code])
            else:  # disconnected connector, unknown employee, unsupported version, ...
                self._finish(job, JobStatus.FAILED, category="configuration", message=error)
        else:
            self._finish(job, JobStatus.SUCCEEDED, external_id=result.external_id)

    @staticmethod
    def _finish(
        job: SynchronizationJob,
        status: JobStatus,
        *,
        external_id: str | None = None,
        category: str | None = None,
        message: object | None = None,
    ) -> None:
        job.status = status
        job.finished_at = _now()
        if external_id is not None:
            job.external_id = external_id
        job.error_category = category
        if message is not None:
            text = getattr(message, "message", None) or str(message)
            job.error_message = text[:500]
