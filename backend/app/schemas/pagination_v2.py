"""API v2 response envelope and sort options."""

import enum

from pydantic import BaseModel, Field


class EmployeeSortV2(enum.StrEnum):
    """Sorts that support cursor pagination. A leading "-" means descending."""

    LAST_NAME = "last_name"
    JOINING_DATE = "joining_date"
    CREATED_AT_DESC = "-created_at"


class CursorPageInfo(BaseModel):
    limit: int
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )
    has_more: bool


class CursorPage[T](BaseModel):
    """One page of a cursor-paginated list."""

    data: list[T]
    page: CursorPageInfo
