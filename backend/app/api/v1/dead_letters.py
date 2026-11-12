"""Dead-letter queue endpoints: /api/v1/organizations/{organization_id}/dead-letter-events/*

Reading the queue needs `events:read` (every role). Replaying needs `events:replay`
(Integration Manager and Organization Admin): a replay makes real calls to external
applications, so read-only viewers cannot trigger it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, require_org_permission
from app.api.v1.events import event_fields
from app.models import DeadLetterEvent, DeadLetterStatus, IntegrationEvent
from app.repositories.dead_letters import DeadLetterRepository
from app.schemas.common import Limit, Offset, Page
from app.schemas.dead_letters import DeadLetterDetailResponse, DeadLetterResponse
from app.schemas.events import EventResponse
from app.security.authorization import OrgContext, Permission
from app.services.dead_letters import DeadLetterService

router = APIRouter(
    prefix="/organizations/{organization_id}/dead-letter-events", tags=["dead-letter queue"]
)

CanReadEvents = Annotated[OrgContext, Depends(require_org_permission(Permission.EVENTS_READ))]
CanReplay = Annotated[OrgContext, Depends(require_org_permission(Permission.EVENTS_REPLAY))]

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Member, but role lacks the required permission"},
    404: {"description": "Organization or entry not found, or caller is not a member"},
}


def _response(entry: DeadLetterEvent, event: IntegrationEvent) -> DeadLetterResponse:
    return DeadLetterResponse(
        id=entry.id,
        event_id=entry.event_id,
        event_type=event.event_type,
        employee_id=event.employee_id,
        reason=entry.reason,
        job_id=entry.job_id,
        connector_id=entry.connector_id,
        operation=entry.operation,
        error_category=entry.error_category,
        error_code=entry.error_code,
        http_status=entry.http_status,
        error_message=entry.error_message,
        attempts=entry.attempts,
        failed_steps=entry.failed_steps,
        dead_lettered_at=entry.dead_lettered_at,
        status=entry.status,
        replayed_at=entry.replayed_at,
        replayed_by_user_id=entry.replayed_by_user_id,
    )


@router.get("", response_model=Page[DeadLetterResponse], responses=_ERRORS)
def list_dead_letters(
    access: CanReadEvents,
    db: DbSession,
    entry_status: DeadLetterStatus | None = None,
    connector_id: uuid.UUID | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[DeadLetterResponse]:
    """The dead-letter queue, newest first. `entry_status=open` shows what needs attention."""
    repository = DeadLetterRepository(db)
    entries, total = repository.list(
        access.organization.id,
        status=entry_status,
        connector_id=connector_id,
        limit=limit,
        offset=offset,
    )
    events = repository.events(access.organization.id, [e.event_id for e in entries])
    return Page(
        items=[_response(e, events[e.event_id]) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{entry_id}", response_model=DeadLetterDetailResponse, responses=_ERRORS)
def get_dead_letter(
    entry_id: uuid.UUID, access: CanReadEvents, db: DbSession
) -> DeadLetterDetailResponse:
    """One entry: the preserved error, the event's current state, and every earlier round."""
    entry = DeadLetterService(db).get(access.organization, entry_id)
    repository = DeadLetterRepository(db)
    event = repository.event(access.organization.id, entry.event_id)
    history = repository.history(access.organization.id, entry.event_id)
    return DeadLetterDetailResponse(
        **_response(entry, event).model_dump(),
        event=EventResponse(**event_fields(event)),
        history=[_response(h, event) for h in history],
    )


@router.post(
    "/{entry_id}/replay",
    response_model=DeadLetterResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_ERRORS,
        409: {
            "description": "Already replayed (`already_replayed`), or no failed workflow "
            "is active (`workflow_inactive`)"
        },
    },
)
def replay_dead_letter(entry_id: uuid.UUID, access: CanReplay, db: DbSession) -> DeadLetterResponse:
    """Send the event back for processing. Accepted, not finished: a worker picks it up.

    Only the failed steps (and those skipped because of them) run again, each with a
    fresh retry budget; steps that succeeded are not repeated. Follow progress with
    `GET /events/{event_id}`. If it fails again, a new entry appears in the queue."""
    entry = DeadLetterService(db).replay(access.organization, entry_id, access.user)
    event = DeadLetterRepository(db).event(access.organization.id, entry.event_id)
    return _response(entry, event)
