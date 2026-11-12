"""Audit log endpoint: /api/v1/organizations/{organization_id}/audit-logs

Read-only by design: entries are written by the services that make changes, in the same
transaction, and can be neither edited nor deleted through the application (or, thanks
to a trigger, through SQL). Requires `audit:read` (Organization Admin, Integration
Manager).
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_org_permission
from app.models import AuditOutcome
from app.repositories.audit import AuditFilters, AuditRepository
from app.schemas.audit import AuditLogResponse
from app.schemas.common import Limit, Offset, Page
from app.security.authorization import OrgContext, Permission

router = APIRouter(prefix="/organizations/{organization_id}/audit-logs", tags=["audit log"])

CanReadAudit = Annotated[OrgContext, Depends(require_org_permission(Permission.AUDIT_READ))]


@router.get(
    "",
    response_model=Page[AuditLogResponse],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Member, but role lacks `audit:read`"},
        404: {"description": "Organization not found, or caller is not a member"},
    },
)
def list_audit_logs(
    access: CanReadAudit,
    db: DbSession,
    action: Annotated[
        str | None,
        Query(
            max_length=60,
            description="Exact action (`employee.updated`) or a prefix ending in a dot "
            "(`employee.`).",
        ),
    ] = None,
    resource_type: Annotated[str | None, Query(max_length=40)] = None,
    resource_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_user_id: uuid.UUID | None = None,
    outcome: AuditOutcome | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[AuditLogResponse]:
    """The organization's audit trail, newest first."""
    entries, total = AuditRepository(db).list(
        access.organization.id,
        AuditFilters(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_user_id=actor_user_id,
            outcome=outcome,
            since=since,
            until=until,
        ),
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[AuditLogResponse.model_validate(e) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )
