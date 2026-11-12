"""Data integrity endpoints (all under /api/v1/organizations/{organization_id}):

* GET  /data-source-policies               effective policy per field   conflicts:read
* PUT  /data-source-policies/{field}       configure one field          policies:manage
* POST /connectors/{connector_id}/reconcile compare with the application conflicts:resolve
* GET  /conflicts                          list, filtered               conflicts:read
* GET  /conflicts/{conflict_id}            one conflict + its history   conflicts:read
* POST /conflicts/{conflict_id}/resolve    decide                       conflicts:resolve
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.deps import DbSession, require_org_permission
from app.models import (
    ConflictSeverity,
    ConflictStatus,
    DataConflict,
    ResolutionKind,
)
from app.schemas.common import Limit, Offset, Page
from app.schemas.conflicts import (
    ConflictDetailResponse,
    ConflictField,
    ConflictResponse,
    PolicyResponse,
    PolicyUpdate,
    ReconcileResponse,
    ResolutionResponse,
    ResolveRequest,
)
from app.security.authorization import OrgContext, Permission
from app.services.conflicts import ConflictService

router = APIRouter(prefix="/organizations/{organization_id}", tags=["data integrity"])

CanRead = Annotated[OrgContext, Depends(require_org_permission(Permission.CONFLICTS_READ))]
CanResolve = Annotated[OrgContext, Depends(require_org_permission(Permission.CONFLICTS_RESOLVE))]
CanManagePolicies = Annotated[
    OrgContext, Depends(require_org_permission(Permission.POLICIES_MANAGE))
]

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Member, but role lacks the required permission"},
    404: {"description": "Organization, connector, field or conflict not found"},
}


@router.get("/data-source-policies", response_model=list[PolicyResponse], responses=_ERRORS)
def list_policies(access: CanRead, db: DbSession) -> list[PolicyResponse]:
    """Which side is authoritative for each field, its severity and resolution mode.
    Fields without a configured policy show the built-in default (`configured: false`)."""
    return [
        PolicyResponse(**p.__dict__)
        for p in ConflictService(db).policies(access.organization).values()
    ]


@router.put(
    "/data-source-policies/{field}",
    response_model=PolicyResponse,
    responses=_ERRORS | {422: {"description": "connector_id missing or given wrongly"}},
)
def set_policy(
    field: ConflictField, payload: PolicyUpdate, access: CanManagePolicies, db: DbSession
) -> PolicyResponse:
    """Configure one field (Organization Admins). Applies to conflicts detected from now
    on; open conflicts keep the authority recorded when they were detected."""
    policy = ConflictService(db).set_policy(
        access.organization,
        field,
        source=payload.source,
        connector_id=payload.connector_id,
        resolution_mode=payload.resolution_mode,
        severity=payload.severity,
    )
    return PolicyResponse(**policy.__dict__)


@router.post(
    "/connectors/{connector_id}/reconcile",
    response_model=ReconcileResponse,
    responses=_ERRORS | {409: {"description": "Connector disconnected"}},
)
def reconcile(connector_id: uuid.UUID, access: CanResolve, db: DbSession) -> ReconcileResponse:
    """Read every account linked to this connector from the application and compare it
    with SyncForge. Differences become conflicts (or are fixed at once where the field's
    policy is `auto`); nothing is overwritten silently. Up to 500 accounts per run."""
    result = ConflictService(db).reconcile(access.organization, connector_id)
    return ReconcileResponse(**result.__dict__)


@router.get("/conflicts", response_model=Page[ConflictResponse], responses=_ERRORS)
def list_conflicts(
    access: CanRead,
    db: DbSession,
    conflict_status: ConflictStatus | None = None,
    severity: ConflictSeverity | None = None,
    field: ConflictField | None = None,
    employee_id: uuid.UUID | None = None,
    connector_id: uuid.UUID | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[ConflictResponse]:
    """Conflicts, most recently detected first. `conflict_status=open` is the work queue."""
    conditions = [DataConflict.organization_id == access.organization.id]
    for column, value in (
        (DataConflict.status, conflict_status),
        (DataConflict.severity, severity),
        (DataConflict.field, field),
        (DataConflict.employee_id, employee_id),
        (DataConflict.connector_id, connector_id),
    ):
        if value is not None:
            conditions.append(column == value)
    total = db.scalar(select(func.count()).select_from(DataConflict).where(*conditions))
    items = db.scalars(
        select(DataConflict)
        .where(*conditions)
        .order_by(DataConflict.last_detected_at.desc(), DataConflict.id)
        .limit(limit)
        .offset(offset)
    )
    return Page(
        items=[ConflictResponse.model_validate(c) for c in items],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


def _detail(service: ConflictService, conflict: DataConflict) -> ConflictDetailResponse:
    return ConflictDetailResponse(
        **ConflictResponse.model_validate(conflict).model_dump(),
        resolutions=[ResolutionResponse.model_validate(r) for r in service.resolutions(conflict)],
    )


@router.get("/conflicts/{conflict_id}", response_model=ConflictDetailResponse, responses=_ERRORS)
def get_conflict(conflict_id: uuid.UUID, access: CanRead, db: DbSession) -> ConflictDetailResponse:
    """One conflict with its resolution history."""
    service = ConflictService(db)
    return _detail(service, service.get(access.organization, conflict_id))


@router.post(
    "/conflicts/{conflict_id}/resolve",
    response_model=ConflictDetailResponse,
    responses=_ERRORS
    | {
        409: {"description": "`conflict_not_open`, or `conflict_stale` (values changed)"},
        422: {
            "description": "`resolution_against_policy`, `note_required`, "
            "`department_not_found`, `reactivation_not_supported`"
        },
        502: {"description": "The application refused the change (normalized error)"},
    },
)
def resolve_conflict(
    conflict_id: uuid.UUID, payload: ResolveRequest, access: CanResolve, db: DbSession
) -> ConflictDetailResponse:
    """Decide a conflict.

    * `use_syncforge`: push SyncForge's value to the application;
    * `use_external`: adopt the application's value in SyncForge (an ordinary, audited
      employee update that also propagates to the other applications; needs
      `employees:write` except for `account_active`);
    * `dismiss`: accept the difference, change nothing (note required).

    Choosing the non-authoritative side needs `override: true` and a note."""
    service = ConflictService(db)
    conflict = service.resolve(
        access.organization,
        conflict_id,
        resolution=ResolutionKind(payload.resolution),
        actor=access.user,
        note=payload.note,
        override=payload.override,
        can_write_employees=access.can(Permission.EMPLOYEES_WRITE),
    )
    return _detail(service, conflict)
