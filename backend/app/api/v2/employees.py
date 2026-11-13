"""API v2: employee list with cursor (keyset) pagination.

What changed from v1, and why it needs a new version: v1 returns
`{items, total, limit, offset}` and pages with OFFSET. v2 returns
`{data, page: {limit, next_cursor, has_more}}` and pages with an opaque cursor. That is a
breaking change for clients (a different response shape and paging model), so it is a
new version instead of an edit to v1. v1 keeps working unchanged.

Why: with OFFSET, a row inserted or deleted before the current position while a client
pages through shifts every later page (duplicates or gaps), and the database reads and
discards all skipped rows. Keyset pagination continues strictly after the last row seen,
so neither happens. The price: no total count and no jumping to page N.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import InstrumentedAttribute

from app.api.deps import DbSession, require_org_permission
from app.api.v2.pagination import decode_cursor, encode_cursor, fingerprint
from app.core.errors import UnprocessableError
from app.models import Employee, EmploymentStatus
from app.repositories.employees import EmployeeFilters, EmployeeRepository
from app.schemas.employees import EmployeeResponse
from app.schemas.pagination_v2 import CursorPage, CursorPageInfo, EmployeeSortV2
from app.security.authorization import OrgContext, Permission

router = APIRouter(prefix="/organizations/{organization_id}/employees", tags=["employees (v2)"])

CanReadEmployees = Annotated[OrgContext, Depends(require_org_permission(Permission.EMPLOYEES_READ))]

# Sort key columns (the ID last, so the key is unique), their direction, and how a
# cursor value is turned back into a typed value.
_SORTS: dict[EmployeeSortV2, tuple[list[InstrumentedAttribute[Any]], bool, list[Any]]] = {
    EmployeeSortV2.LAST_NAME: (
        [Employee.last_name, Employee.first_name, Employee.id],
        False,
        [str, str, uuid.UUID],
    ),
    EmployeeSortV2.JOINING_DATE: (
        [Employee.joining_date, Employee.id],
        False,
        [date.fromisoformat, uuid.UUID],
    ),
    EmployeeSortV2.CREATED_AT_DESC: (
        [Employee.created_at, Employee.id],
        True,
        [datetime.fromisoformat, uuid.UUID],
    ),
}


def _key_of(employee: Employee, columns: list[InstrumentedAttribute[Any]]) -> list[str]:
    values = [getattr(employee, c.key) for c in columns]
    return [v.isoformat() if isinstance(v, (date, datetime)) else str(v) for v in values]


@router.get(
    "",
    response_model=CursorPage[EmployeeResponse],
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Role lacks employees:read"},
        404: {"description": "Organization not found, or caller is not a member"},
        422: {"description": "Invalid parameters, or `invalid_cursor`"},
    },
)
def list_employees_v2(
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
    sort: EmployeeSortV2 = EmployeeSortV2.LAST_NAME,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[
        str | None,
        Query(
            max_length=1000,
            description="`page.next_cursor` from the previous response. Omit for the first "
            "page. Must be used with the same filters and sort.",
        ),
    ] = None,
) -> CursorPage[EmployeeResponse]:
    """List employees, paged with a cursor. Same filters as v1; no `offset`, no `total`.

    Follow `page.next_cursor` until `page.has_more` is false. Employees added or removed
    while paging never cause duplicates or skipped rows among the others."""
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
    query_fingerprint = fingerprint({"organization": access.organization.id, **filters.__dict__})
    columns, descending, parsers = _SORTS[sort]

    after: list[Any] | None = None
    if cursor is not None:
        raw = decode_cursor(cursor, sort=sort.value, filters_fingerprint=query_fingerprint)
        try:
            if len(raw) != len(parsers):
                raise ValueError("wrong key length")
            after = [parse(value) for parse, value in zip(parsers, raw, strict=True)]
        except ValueError as exc:
            raise UnprocessableError(
                "The cursor is not valid. Start again without a cursor.", code="invalid_cursor"
            ) from exc

    rows, has_more = EmployeeRepository(db).list_after(
        access.organization.id,
        filters,
        key_columns=columns,
        descending=descending,
        after=after,
        limit=limit,
    )
    next_cursor = (
        encode_cursor(sort.value, _key_of(rows[-1], columns), query_fingerprint)
        if has_more
        else None
    )
    return CursorPage(
        data=[EmployeeResponse.model_validate(e) for e in rows],
        page=CursorPageInfo(limit=limit, next_cursor=next_cursor, has_more=has_more),
    )
