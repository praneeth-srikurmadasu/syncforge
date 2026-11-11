"""Department endpoints: /api/v1/organizations/{organization_id}/departments/*"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import DbSession, require_org_permission
from app.models import Department
from app.repositories.employees import DepartmentRepository
from app.schemas.common import Limit, Offset, Page
from app.schemas.employees import DepartmentCreate, DepartmentResponse, DepartmentUpdate
from app.security.authorization import OrgContext, Permission
from app.services.employees import DepartmentService

router = APIRouter(prefix="/organizations/{organization_id}/departments", tags=["departments"])

CanReadDepartments = Annotated[
    OrgContext, Depends(require_org_permission(Permission.DEPARTMENTS_READ))
]
CanManageDepartments = Annotated[
    OrgContext, Depends(require_org_permission(Permission.DEPARTMENTS_MANAGE))
]

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Member, but role lacks the required permission"},
    404: {"description": "Organization (or department) not found, or caller is not a member"},
}


def _response(department: Department, employee_count: int) -> DepartmentResponse:
    return DepartmentResponse(
        id=department.id,
        name=department.name,
        employee_count=employee_count,
        created_at=department.created_at,
    )


@router.get("", response_model=Page[DepartmentResponse], responses=_ERRORS)
def list_departments(
    access: CanReadDepartments, db: DbSession, limit: Limit = 50, offset: Offset = 0
) -> Page[DepartmentResponse]:
    rows, total = DepartmentRepository(db).list_with_counts(
        access.organization.id, limit=limit, offset=offset
    )
    return Page(
        items=[_response(d, count) for d, count in rows], total=total, limit=limit, offset=offset
    )


@router.post(
    "",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS | {409: {"description": "Name already used (case-insensitive)"}},
)
def create_department(
    payload: DepartmentCreate, access: CanManageDepartments, db: DbSession
) -> DepartmentResponse:
    department = DepartmentService(db).create(access.organization, name=payload.name)
    return _response(department, 0)


@router.patch(
    "/{department_id}",
    response_model=DepartmentResponse,
    responses=_ERRORS | {409: {"description": "Name already used (case-insensitive)"}},
)
def rename_department(
    department_id: uuid.UUID,
    payload: DepartmentUpdate,
    access: CanManageDepartments,
    db: DbSession,
) -> DepartmentResponse:
    service = DepartmentService(db)
    department = service.rename(access.organization, department_id, name=payload.name)
    return _response(department, service.employee_count(access.organization, department))


@router.delete(
    "/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS | {409: {"description": "Department still has employees"}},
)
def delete_department(
    department_id: uuid.UUID, access: CanManageDepartments, db: DbSession
) -> Response:
    DepartmentService(db).delete(access.organization, department_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
