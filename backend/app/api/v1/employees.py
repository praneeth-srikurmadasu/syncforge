"""Employee endpoints: /api/v1/organizations/{organization_id}/employees/*

Employees are always addressed through their organization. Combined with
`require_org_permission`, an employee ID from another organization behaves exactly
like an ID that does not exist (404).
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_org_permission
from app.core.config import get_settings
from app.core.errors import ConflictError, UnprocessableError
from app.models import Employee, EmploymentStatus
from app.reliability.idempotency import REPLAY_HEADER, IdempotencyStore, StoredResponse
from app.repositories.employees import EmployeeFilters, EmployeeRepository, EmployeeSort
from app.schemas.common import Limit, Offset, Page
from app.schemas.employees import (
    EmployeeCreate,
    EmployeeResponse,
    EmployeeTerminate,
    EmployeeUpdate,
)
from app.security.authorization import OrgContext, Permission
from app.services.employees import EmployeeService

router = APIRouter(prefix="/organizations/{organization_id}/employees", tags=["employees"])

CanReadEmployees = Annotated[OrgContext, Depends(require_org_permission(Permission.EMPLOYEES_READ))]
CanWriteEmployees = Annotated[
    OrgContext, Depends(require_org_permission(Permission.EMPLOYEES_WRITE))
]

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Member, but role lacks the required permission"},
    404: {"description": "Organization or employee not found, or caller is not a member"},
}
_WRITE_ERRORS = _ERRORS | {
    409: {"description": "Duplicate employee number/email, or employee is terminated"},
    422: {"description": "Invalid input, unknown department/manager, or manager cycle"},
}
_PRECONDITION = {
    412: {"description": "`version_conflict`: If-Match was sent and the employee changed since"}
}


@router.get("", response_model=Page[EmployeeResponse], responses=_ERRORS)
def list_employees(
    access: CanReadEmployees,
    db: DbSession,
    search: Annotated[
        str | None,
        Query(min_length=1, max_length=100, description="Matches name, email or employee number."),
    ] = None,
    department_id: uuid.UUID | None = None,
    manager_id: uuid.UUID | None = None,
    employment_status: EmploymentStatus | None = None,
    location: Annotated[str | None, Query(max_length=150)] = None,
    joined_from: date | None = None,
    joined_to: date | None = None,
    include_archived: bool = False,
    sort: EmployeeSort = EmployeeSort.LAST_NAME,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[EmployeeResponse]:
    """List employees with search, filters, sorting and offset pagination.

    Archived employees are excluded unless `include_archived=true`.
    """
    if joined_from and joined_to and joined_from > joined_to:
        raise UnprocessableError(
            "joined_from must be on or before joined_to.", code="invalid_date_range"
        )
    filters = EmployeeFilters(
        search=search.strip() if search else None,
        department_id=department_id,
        manager_id=manager_id,
        employment_status=employment_status,
        location=location.strip() if location else None,
        joined_from=joined_from,
        joined_to=joined_to,
        include_archived=include_archived,
    )
    employees, total = EmployeeRepository(db).list(
        access.organization.id, filters, sort=sort, limit=limit, offset=offset
    )
    return Page(
        items=[EmployeeResponse.model_validate(e) for e in employees],
        total=total,
        limit=limit,
        offset=offset,
    )


def _parse_if_match(
    if_match: Annotated[
        str | None,
        Header(
            alias="If-Match",
            max_length=40,
            description='Optional. The ETag (version) you last read, e.g. `"3"`. The change '
            "is refused with 412 if the employee changed since. `*` matches any version.",
        ),
    ] = None,
) -> int | None:
    if if_match is None or if_match.strip() == "*":
        return None
    value = if_match.strip()
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    if not value.isdigit():
        raise UnprocessableError(
            'If-Match must be an ETag returned by this API, e.g. "3".', code="invalid_if_match"
        )
    return int(value)


IfMatch = Annotated[int | None, Depends(_parse_if_match)]


def _with_etag(response: Response, employee: Employee) -> EmployeeResponse:
    response.headers["ETag"] = f'"{employee.version}"'
    return EmployeeResponse.model_validate(employee)


IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=r"^[\x21-\x7e]+$",  # printable ASCII, no spaces
        description="Optional. Send a unique value (e.g. a UUID) to make retries safe: a "
        "repeat of the same request with the same key returns the first response "
        "(header `Idempotent-Replayed: true`) instead of creating a second employee. "
        "Stored for IDEMPOTENCY_TTL_HOURS (default 24).",
    ),
]


@router.post(
    "",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_WRITE_ERRORS
    | {422: {"description": "Invalid data, or `idempotency_key_reused` for a different request"}},
)
def create_employee(
    payload: EmployeeCreate,
    access: CanWriteEmployees,
    db: DbSession,
    response: Response,
    idempotency_key: IdempotencyKey = None,
) -> EmployeeResponse | JSONResponse:
    """Create an employee. Emits `employee.created`. Supports `Idempotency-Key`."""
    service = EmployeeService(db)
    if idempotency_key is None:
        return _with_etag(response, service.create(access.organization, payload))

    store = IdempotencyStore(
        db,
        organization_id=access.organization.id,
        user_id=access.user.id,
        key=idempotency_key,
        endpoint="POST /employees",
        body=payload.model_dump(mode="json"),
        ttl_hours=get_settings().idempotency_ttl_hours,
    )
    stored = store.lookup()
    if stored is not None:
        return _replay(stored)

    def remember(employee: Employee) -> None:
        body = EmployeeResponse.model_validate(employee).model_dump(mode="json")
        store.stage(status.HTTP_201_CREATED, body, employee.id)

    try:
        employee = service.create(access.organization, payload, before_commit=remember)
    except (ConflictError, IntegrityError):
        stored = store.after_conflict()  # an identical concurrent request won the race
        if stored is not None:
            return _replay(stored)
        raise
    return _with_etag(response, employee)


def _replay(stored: StoredResponse) -> JSONResponse:
    headers = {REPLAY_HEADER: "true"}
    if "version" in stored.body:
        headers["ETag"] = f'"{stored.body["version"]}"'
    return JSONResponse(stored.body, status_code=stored.status_code, headers=headers)


@router.get("/{employee_id}", response_model=EmployeeResponse, responses=_ERRORS)
def get_employee(
    employee_id: uuid.UUID, access: CanReadEmployees, db: DbSession, response: Response
) -> EmployeeResponse:
    """Get one employee, including archived ones. The `ETag` header carries its version."""
    employee = EmployeeService(db).get(access.organization, employee_id)
    return _with_etag(response, employee)


@router.patch(
    "/{employee_id}", response_model=EmployeeResponse, responses=_WRITE_ERRORS | _PRECONDITION
)
def update_employee(
    employee_id: uuid.UUID,
    payload: EmployeeUpdate,
    access: CanWriteEmployees,
    db: DbSession,
    response: Response,
    if_match: IfMatch = None,
) -> EmployeeResponse:
    """Partially update an employee.

    Emits `employee.department_changed`, `employee.manager_changed` and/or
    `employee.updated` depending on what changed. To terminate, use `/terminate`.

    Send `If-Match: "<version>"` (the ETag you received) to make the update conditional:
    if someone changed the employee meanwhile, the response is `412 version_conflict`
    and nothing is changed."""
    employee = EmployeeService(db).update(
        access.organization, employee_id, payload.changes(), expected_version=if_match
    )
    return _with_etag(response, employee)


@router.post(
    "/{employee_id}/terminate",
    response_model=EmployeeResponse,
    responses=_ERRORS
    | {
        409: {"description": "Employee is already terminated"},
        422: {"description": "Termination date before joining date"},
    }
    | _PRECONDITION,
)
def terminate_employee(
    employee_id: uuid.UUID,
    access: CanWriteEmployees,
    db: DbSession,
    response: Response,
    payload: Annotated[EmployeeTerminate | None, Body()] = None,
    if_match: IfMatch = None,
) -> EmployeeResponse:
    """Terminate an employee (final). Direct reports move to the employee's manager.

    Emits `employee.terminated`, plus `employee.manager_changed` for each moved report.
    """
    termination_date = payload.termination_date if payload else None
    employee = EmployeeService(db).terminate(
        access.organization,
        employee_id,
        termination_date=termination_date,
        expected_version=if_match,
    )
    return _with_etag(response, employee)


@router.delete(
    "/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS | {409: {"description": "Employee is not terminated"}} | _PRECONDITION,
)
def archive_employee(
    employee_id: uuid.UUID, access: CanWriteEmployees, db: DbSession, if_match: IfMatch = None
) -> Response:
    """Archive (soft-delete) a terminated employee. The record is kept for history and
    still returned by GET; it is hidden from lists unless `include_archived=true`."""
    EmployeeService(db).archive(access.organization, employee_id, expected_version=if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
