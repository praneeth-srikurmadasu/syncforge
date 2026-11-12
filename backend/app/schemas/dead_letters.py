"""Dead-letter queue schemas.

Like events, entries never contain employee data: the error message comes from the
external application's error normalization, which carries no request payloads, and
the event is identified by ID and type only.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import DeadLetterReason, DeadLetterStatus
from app.schemas.events import EventResponse


class DeadLetterResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    employee_id: uuid.UUID
    reason: DeadLetterReason = Field(
        description="`retries_exhausted`: a temporary error outlasted the retry budget. "
        "`non_retryable`: retrying would not help (credentials, permissions, invalid data, "
        "configuration)."
    )
    job_id: uuid.UUID | None = Field(description="The first step that failed for good.")
    connector_id: uuid.UUID | None
    operation: str | None
    error_category: str | None
    error_code: str | None
    http_status: int | None
    error_message: str | None
    attempts: int = Field(description="Attempts the failed step made in this round.")
    failed_steps: int
    dead_lettered_at: datetime
    status: DeadLetterStatus
    replayed_at: datetime | None
    replayed_by_user_id: uuid.UUID | None


class DeadLetterDetailResponse(DeadLetterResponse):
    event: EventResponse
    history: list[DeadLetterResponse] = Field(
        description="Every dead-letter round of this event, oldest first (includes this one)."
    )
