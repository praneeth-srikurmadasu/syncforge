"""Observability endpoints.

* GET /api/v1/organizations/{organization_id}/summary - the dashboard's figures and
  processing durations in one request (`org:read`).
* GET /api/v1/system/status - background processing across the platform: heartbeats of
  workers and the relay, outbox backlog, stuck events (Super Admins only).

Neither is a readiness probe: /ready stays database-only, so a stopped worker never takes
the API out of service (events wait in the outbox).
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, require_org_permission
from app.core.config import get_settings
from app.core.errors import PermissionDeniedError
from app.monitoring.status import system_status
from app.monitoring.summary import organization_summary
from app.schemas.monitoring import OrganizationSummaryResponse, SystemStatusResponse
from app.security.authorization import OrgContext, Permission

router = APIRouter(tags=["monitoring"])

CanReadOrg = Annotated[OrgContext, Depends(require_org_permission(Permission.ORG_READ))]


@router.get(
    "/organizations/{organization_id}/summary",
    response_model=OrganizationSummaryResponse,
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Organization not found, or caller is not a member"},
    },
)
def get_organization_summary(access: CanReadOrg, db: DbSession) -> OrganizationSummaryResponse:
    """Counts of employees, workflows, connectors, events, open dead letters and open
    conflicts, plus event processing durations over the last 24 hours. Each count equals
    the `total` of the matching list endpoint."""
    return OrganizationSummaryResponse.model_validate(
        organization_summary(db, access.organization.id)
    )


@router.get(
    "/system/status",
    response_model=SystemStatusResponse,
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Caller is not a Super Admin"},
    },
)
def get_system_status(user: CurrentUser, db: DbSession) -> SystemStatusResponse:
    """Whether workers and the outbox relay are alive and keeping up. `healthy` is false
    when no worker or no relay has reported within HEARTBEAT_STALE_AFTER_SECONDS, or when
    events are past their processing lease."""
    if not user.is_superadmin:
        raise PermissionDeniedError(
            "Only Super Admins can read the platform status.", code="superadmin_required"
        )
    return SystemStatusResponse.model_validate(system_status(db, get_settings()))
