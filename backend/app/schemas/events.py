"""Integration event schemas.

Events expose *which* fields changed, never the old or new values: the values (names,
emails, ...) stay in the database for the workers, and the employee API already shows
the current data to those allowed to see it.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import IntegrationEventStatus
from app.schemas.workflows import ExecutionResponse


class EventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    employee_id: uuid.UUID
    changed_fields: list[str]
    status: IntegrationEventStatus
    correlation_id: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_error: str | None


class EventDetailResponse(EventResponse):
    executions: list[ExecutionResponse]
