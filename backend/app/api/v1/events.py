"""Integration event endpoints: /api/v1/organizations/{organization_id}/events/*

Read-only. Events are created by employee changes (transactional outbox) and processed
by background workers; these endpoints show where each event is and what it did.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_org_permission
from app.api.v1.workflows import execution_response
from app.core.errors import NotFoundError
from app.models import IntegrationEvent, IntegrationEventStatus
from app.repositories.workflows import EventFilters, EventRepository, ExecutionRepository
from app.schemas.common import Limit, Offset, Page
from app.schemas.events import AttemptResponse, EventDetailResponse, EventResponse
from app.schemas.workflows import TriggerEventType
from app.security.authorization import OrgContext, Permission

router = APIRouter(prefix="/organizations/{organization_id}/events", tags=["events"])

CanReadEvents = Annotated[OrgContext, Depends(require_org_permission(Permission.EVENTS_READ))]

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Member, but role lacks the required permission"},
    404: {"description": "Organization or event not found, or caller is not a member"},
}


def _fields(event: IntegrationEvent) -> dict:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "employee_id": event.employee_id,
        "changed_fields": sorted(event.payload.get("changes", {})),
        "status": event.status,
        "correlation_id": event.correlation_id,
        "attempts": event.attempts,
        "next_attempt_at": event.next_attempt_at,
        "created_at": event.created_at,
        "started_at": event.started_at,
        "completed_at": event.completed_at,
        "last_error": event.last_error,
    }


@router.get("", response_model=Page[EventResponse], responses=_ERRORS)
def list_events(
    access: CanReadEvents,
    db: DbSession,
    event_status: IntegrationEventStatus | None = None,
    event_type: TriggerEventType | None = None,
    employee_id: uuid.UUID | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[EventResponse]:
    """Events, newest first. Filter by processing status, type or employee.

    `retrying` events have a step waiting for its next attempt (`next_attempt_at`)."""
    events, total = EventRepository(db).list(
        access.organization.id,
        EventFilters(status=event_status, event_type=event_type, employee_id=employee_id),
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[EventResponse(**_fields(e)) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{event_id}", response_model=EventDetailResponse, responses=_ERRORS)
def get_event(event_id: uuid.UUID, access: CanReadEvents, db: DbSession) -> EventDetailResponse:
    """One event with every workflow execution it triggered and each step's status."""
    event = EventRepository(db).get(access.organization.id, event_id)
    if event is None:
        raise NotFoundError("Event not found.", code="event_not_found")
    executions = ExecutionRepository(db).for_event(access.organization.id, event.id)
    return EventDetailResponse(
        **_fields(event), executions=[execution_response(*row) for row in executions]
    )


@router.get("/{event_id}/attempts", response_model=list[AttemptResponse], responses=_ERRORS)
def list_attempts(
    event_id: uuid.UUID, access: CanReadEvents, db: DbSession
) -> list[AttemptResponse]:
    """Every external call made for this event, in order: the retry history.

    Grouped by execution, then step position, then attempt number."""
    event = EventRepository(db).get(access.organization.id, event_id)
    if event is None:
        raise NotFoundError("Event not found.", code="event_not_found")
    return [
        AttemptResponse(
            job_id=job.id,
            execution_id=job.execution_id,
            position=job.position,
            connector_id=job.connector_id,
            operation=job.operation,
            attempt_number=attempt.attempt_number,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            duration_ms=attempt.duration_ms,
            outcome=attempt.outcome,
            error_category=attempt.error_category,
            error_code=attempt.error_code,
            error_message=attempt.error_message,
            http_status=attempt.http_status,
            retryable=attempt.retryable,
            retry_after_seconds=attempt.retry_after_seconds,
            next_attempt_at=attempt.next_attempt_at,
        )
        for attempt, job in ExecutionRepository(db).attempts_for_event(
            access.organization.id, event.id
        )
    ]
