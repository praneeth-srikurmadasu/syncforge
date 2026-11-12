"""Platform security events: /api/v1/security-events (Super Admins only).

Sign-ins are not organization-scoped, so this is a platform view, not part of any
organization's audit log. Members see their own history at /api/v1/auth/activity.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.core.errors import PermissionDeniedError
from app.models import SecurityEventType
from app.schemas.common import Limit, Offset, Page
from app.schemas.security_events import SecurityEventResponse
from app.security.security_events import SecurityEventFilters, SecurityEventRepository

router = APIRouter(prefix="/security-events", tags=["security events"])


@router.get(
    "",
    response_model=Page[SecurityEventResponse],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Caller is not a Super Admin"},
    },
)
def list_security_events(
    user: CurrentUser,
    db: DbSession,
    event: SecurityEventType | None = None,
    user_id: uuid.UUID | None = None,
    client_ip: Annotated[str | None, Query(max_length=45)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[SecurityEventResponse]:
    """All security events, newest first, for investigating attacks across accounts."""
    if not user.is_superadmin:
        raise PermissionDeniedError(
            "Only Super Admins can read platform security events.", code="superadmin_required"
        )
    rows, total = SecurityEventRepository(db).list(
        SecurityEventFilters(
            event=event, user_id=user_id, client_ip=client_ip, since=since, until=until
        ),
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[SecurityEventResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
