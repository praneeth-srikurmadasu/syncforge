"""The workflow engine: process one integration event.

Delivery is at-least-once (a message can arrive twice; a worker can die halfway), so
processing is built to be safe to repeat:

1. **Claim.** One atomic UPDATE moves the event to `processing` and sets a lease
   (`locked_until`). It succeeds only if the event is `pending`, `processing` with an
   expired lease (its worker died), or `retrying` with its next attempt due. A duplicate
   delivery of an event another worker owns, of a retry that is not due yet, or of a
   finished event claims nothing and is skipped.
2. **Plan.** For every *active* workflow whose trigger matches, get or create the
   execution for (event, workflow) - a unique constraint makes it exactly one - and copy
   the workflow's steps into synchronization jobs.
3. **Run.** Jobs run in order. A job that already succeeded is skipped, so a resumed
   execution never repeats finished work. The lease is renewed before each job, and no
   database lock is held during the external call. Every external call is recorded as a
   `synchronization_attempts` row, opened before the call and closed after it.
   Before each call the connector's rate limit is checked; a job over the limit is
   deferred to the next minute without using an attempt. The connector's circuit
   breaker may refuse the call (`circuit_open`, retryable, counts as an attempt).
4. **Retry.** A retryable failure (rate limited, timeout, network, server error) with
   attempts left puts the job in `retrying` with a `next_attempt_at` computed by the
   retry policy (exponential backoff with jitter, never earlier than `Retry-After`). Later
   jobs of that execution wait - steps are sequential. Non-retryable failures and
   exhausted attempts fail the job for good.
5. **Finish.** The event becomes `completed` if every execution succeeded (or nothing
   matched), `retrying` (with the earliest `next_attempt_at`) if a job waits for a retry,
   otherwise `dead_letter`: a `dead_letter_events` entry preserves the error until an
   authorized user replays the event (app/reliability/dead_letter.py). The outbox relay
   re-dispatches retrying events when they are due.

Each connector call goes through `ConnectorService.run_operation`, which records the
external account link in its own commit. If a worker dies after the external call but
before the job is marked succeeded, the re-run finds the link and treats `create_user`
as already done instead of creating a second account. If it dies (or the call times
out) *before* the link is recorded, the re-run sends the same idempotency key
(`syncforge-job-<job id>`), and an API that honours keys returns the account it already
created instead of creating another (docs/13).

Reliability building blocks used here live in app/reliability/: retry policy, dead
letter, rate limit; the circuit breaker wraps the call inside ConnectorService.
"""

import logging
import random
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.core.config import Settings, get_settings
from app.core.errors import AppError, BadGatewayError
from app.models import (
    AttemptOutcome,
    AuditOutcome,
    Connector,
    ExecutionStatus,
    IntegrationEvent,
    IntegrationEventStatus,
    JobStatus,
    Organization,
    SynchronizationAttempt,
    SynchronizationJob,
    Workflow,
    WorkflowExecution,
)
from app.reliability.dead_letter import dead_letter
from app.reliability.rate_limit import RateLimiter, rate_limit
from app.reliability.retry import RetryPolicy, decide
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
    outcome: str  # "completed", "retrying", "dead_letter", or "skipped" (not claimable)
    executions: int = 0


def idempotency_key(job: SynchronizationJob) -> str:
    """The same for every attempt (and every replay) of one job: one intended effect."""
    return f"syncforge-job-{job.id}"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _Outcome:
    """What one attempt of a job produced (before the retry decision)."""

    status: JobStatus  # SUCCEEDED, SKIPPED or FAILED
    external_id: str | None = None
    category: str | None = None
    code: str | None = None
    message: str | None = None
    http_status: int | None = None
    retryable: bool = False
    retry_after: float | None = None


class EventProcessor:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self.session = session
        audit.set_actor(session, None)  # the engine always acts as the system
        self.settings = settings or get_settings()
        self.policy = RetryPolicy.from_settings(self.settings)
        self.rng = rng or random.Random()  # noqa: S311 - retry jitter, not security

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

        self._finish_event(event, executions)
        outcome = event.status.value
        logger.info(
            "event processing finished",
            extra={
                **log,
                "outcome": outcome,
                "executions": len(executions),
                "next_attempt_at": event.next_attempt_at.isoformat()
                if event.next_attempt_at
                else None,
            },
        )
        return ProcessResult(event.id, outcome, len(executions))

    def _finish_event(self, event: IntegrationEvent, executions: list[WorkflowExecution]) -> None:
        waiting = [
            job.next_attempt_at
            for execution in executions
            for job in execution.jobs
            if job.status is JobStatus.RETRYING and job.next_attempt_at is not None
        ]
        failed = [e for e in executions if e.status is ExecutionStatus.FAILED]
        event.locked_until = None
        if waiting:
            event.status = IntegrationEventStatus.RETRYING
            event.next_attempt_at = min(waiting)
            event.completed_at = None
        else:
            event.status = (
                IntegrationEventStatus.DEAD_LETTER if failed else IntegrationEventStatus.COMPLETED
            )
            event.next_attempt_at = None
            event.completed_at = _now()
        event.last_error = (
            f"{len(failed)} of {len(executions)} workflow execution(s) failed." if failed else None
        )
        if event.status is IntegrationEventStatus.DEAD_LETTER:
            dead_letter(self.session, event, failed)
        self.session.commit()

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
                    # A due retry. Needed for correctness, not only convenience: the relay
                    # publishes while it holds the row and only then commits "pending".
                    # Under READ COMMITTED an UPDATE whose WHERE does not match the last
                    # committed row version neither waits nor re-checks, so without this
                    # clause a fast worker would see "retrying" and skip the event.
                    (IntegrationEvent.status == IntegrationEventStatus.RETRYING)
                    & (IntegrationEvent.next_attempt_at <= now),
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
        waiting = False
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
            if job.status is JobStatus.RETRYING and job.next_attempt_at > _now():
                waiting = True  # not due yet (another execution's retry woke the event)
                break
            if self._defer_if_throttled(job, log):
                waiting = True  # over the connector's rate limit: wait, no attempt used
                break

            self._attempt(event, organization, job)
            logger.info(
                "synchronization job finished",
                extra={
                    **log,
                    "position": job.position,
                    "operation": job.operation,
                    "connector_id": str(job.connector_id),
                    "status": job.status.value,
                    "attempt": job.attempts,
                    "error_category": job.error_category,
                    "next_attempt_at": job.next_attempt_at.isoformat()
                    if job.next_attempt_at
                    else None,
                },
            )
            if job.status is JobStatus.RETRYING:
                waiting = True  # sequential: later steps wait for this one
                break
            failed = job.status is JobStatus.FAILED

        if waiting:
            self.session.commit()  # execution stays running
            return
        execution.status = ExecutionStatus.FAILED if failed else ExecutionStatus.SUCCEEDED
        execution.finished_at = _now()
        first_failure = next((j for j in execution.jobs if j.status is JobStatus.FAILED), None)
        audit.record(
            self.session,
            organization_id=execution.organization_id,
            action="workflow.executed",
            resource_type="workflow",
            resource_id=execution.workflow_id,
            outcome=AuditOutcome.FAILURE if failed else AuditOutcome.SUCCESS,
            details={
                "execution_id": execution.id,
                "event_id": event.id,
                "event_type": event.event_type,
                "employee_id": event.employee_id,
                "steps": dict(Counter(j.status.value for j in execution.jobs)),
                **(
                    {
                        "failed_position": first_failure.position,
                        "connector_id": first_failure.connector_id,
                        "error_category": first_failure.error_category,
                    }
                    if first_failure
                    else {}
                ),
            },
        )
        self.session.commit()

    def _attempt(
        self, event: IntegrationEvent, organization: Organization, job: SynchronizationJob
    ) -> None:
        """Make one external call for `job`, record it, and decide what happens next."""
        self._close_interrupted_attempts(job)
        self._renew_lease(event)
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.next_attempt_at = None
        job.started_at = _now()
        attempt = SynchronizationAttempt(
            organization_id=job.organization_id,
            attempt_number=job.attempts,
            started_at=job.started_at,
        )
        job.attempt_history.append(attempt)  # keeps the loaded collection current
        self.session.commit()  # visible as running; no lock held during the call

        started = time.perf_counter()
        outcome = self._execute(organization, job)
        finished = _now()
        attempt.finished_at = finished
        attempt.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        attempt.outcome = AttemptOutcome(outcome.status.value)
        attempt.error_category = outcome.category
        attempt.error_code = outcome.code
        attempt.error_message = outcome.message
        attempt.http_status = outcome.http_status
        attempt.retryable = outcome.retryable if outcome.status is JobStatus.FAILED else None
        attempt.retry_after_seconds = outcome.retry_after

        job.finished_at = finished
        job.error_category = outcome.category
        job.error_message = outcome.message
        if outcome.external_id is not None:
            job.external_id = outcome.external_id
        if outcome.status is not JobStatus.FAILED:
            job.status = outcome.status
        else:
            decision = decide(
                self.policy,
                attempts_made=job.attempts - job.attempts_at_last_replay,  # this round
                retryable=outcome.retryable,
                retry_after=outcome.retry_after,
                rng=self.rng,
            )
            if decision.retry:
                job.status = JobStatus.RETRYING
                job.next_attempt_at = finished + timedelta(seconds=decision.delay_seconds or 0)
                attempt.next_attempt_at = job.next_attempt_at
                audit.record(
                    self.session,
                    organization_id=job.organization_id,
                    action="sync.retry_scheduled",
                    resource_type="synchronization_job",
                    resource_id=job.id,
                    outcome=AuditOutcome.FAILURE,  # this attempt failed; another is scheduled
                    details={
                        "event_id": event.id,
                        "connector_id": job.connector_id,
                        "operation": job.operation,
                        "attempt": job.attempts,
                        "error_category": outcome.category,
                        "error_code": outcome.code,
                        "next_attempt_at": job.next_attempt_at,
                    },
                )
            else:
                job.status = JobStatus.FAILED
                if decision.reason == "attempts_exhausted":
                    made = job.attempts - job.attempts_at_last_replay
                    job.error_message = (f"Gave up after {made} attempts: {outcome.message or ''}")[
                        :500
                    ]
        self.session.commit()

    def _defer_if_throttled(self, job: SynchronizationJob, log: dict[str, str]) -> bool:
        """Apply the connector's `rate_limit_per_minute` (app/reliability/rate_limit.py)."""
        connector = self.session.get(Connector, job.connector_id)
        if connector is None:
            return False
        wait = RateLimiter(self.session).acquire(connector)
        if wait is None:
            return False
        job.status = JobStatus.RETRYING
        # Spread the deferred jobs over the first second of the next window.
        job.next_attempt_at = _now() + timedelta(seconds=wait + self.rng.uniform(0, 1))
        job.error_category = "throttled"
        job.error_message = (
            f"Waiting for this connector's rate limit ({rate_limit(connector)} calls/minute)."
        )
        self.session.commit()
        logger.info(
            "synchronization job deferred by rate limit",
            extra={
                **log,
                "position": job.position,
                "connector_id": str(job.connector_id),
                "next_attempt_at": job.next_attempt_at.isoformat(),
            },
        )
        return True

    def _close_interrupted_attempts(self, job: SynchronizationJob) -> None:
        """An attempt left open means a worker stopped during the call (crash, kill)."""
        for previous in job.attempt_history:
            if previous.outcome is None:
                previous.outcome = AttemptOutcome.INTERRUPTED
                previous.finished_at = _now()
                previous.error_message = "The worker stopped during this attempt."

    def _execute(self, organization: Organization, job: SynchronizationJob) -> _Outcome:
        service = ConnectorService(self.session, self.settings)
        try:
            result = service.run_operation(
                organization,
                job.connector_id,
                operation=job.operation,
                employee_id=job.employee_id,
                idempotency_key=idempotency_key(job),
            )
        except BadGatewayError as error:  # the external application failed
            details: dict[str, Any] = error.details or {}
            return _Outcome(
                JobStatus.FAILED,
                category=details.get("category"),
                code=details.get("code"),
                message=error.message[:500],
                http_status=details.get("status_code"),
                retryable=bool(details.get("retryable")),
                retry_after=details.get("retry_after"),
            )
        except AppError as error:
            if error.code == "already_linked" and job.operation == "create_user":
                # Done earlier (e.g. by a run that crashed before recording success).
                return _Outcome(
                    JobStatus.SUCCEEDED, external_id=(error.details or {}).get("external_id")
                )
            if error.code in _SKIP_CODES:
                return _Outcome(JobStatus.SKIPPED, message=_SKIP_CODES[error.code])
            # Disconnected connector, unknown employee, unsupported version, ...: our side,
            # and repeating it will not help until someone changes the configuration.
            return _Outcome(
                JobStatus.FAILED,
                category="configuration",
                code=error.code,
                message=error.message[:500],
            )
        return _Outcome(JobStatus.SUCCEEDED, external_id=result.external_id)
