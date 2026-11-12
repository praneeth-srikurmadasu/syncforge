"""Integration event schemas.

Events expose *which* fields changed, never the old or new values: the values (names,
emails, ...) stay in the database for the workers, and the employee API already shows
the current data to those allowed to see it.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import AttemptOutcome, IntegrationEventStatus, StepOperation
from app.schemas.workflows import ExecutionResponse


class EventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    employee_id: uuid.UUID
    changed_fields: list[str]
    status: IntegrationEventStatus
    correlation_id: str | None
    attempts: int
    next_attempt_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_error: str | None


class EventDetailResponse(EventResponse):
    executions: list[ExecutionResponse]


class AttemptResponse(BaseModel):
    """One external call made for one synchronization job."""

    job_id: uuid.UUID
    execution_id: uuid.UUID
    position: int
    connector_id: uuid.UUID
    operation: StepOperation
    attempt_number: int
    started_at: datetime
    finished_at: datetime | None
    duration_ms: float | None
    outcome: AttemptOutcome | None = Field(
        description="NULL while the call is in progress; `interrupted` if a worker stopped."
    )
    error_category: str | None
    error_code: str | None
    error_message: str | None
    http_status: int | None
    retryable: bool | None
    retry_after_seconds: float | None
    next_attempt_at: datetime | None = Field(
        description="When this failure scheduled the next attempt (NULL if none)."
    )
