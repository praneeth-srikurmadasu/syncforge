"""Shared schema building blocks: pagination."""

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

# Query parameters reused by every list endpoint.
Limit = Annotated[int, Query(ge=1, le=100, description="Page size (1-100).")]
Offset = Annotated[int, Query(ge=0, description="Number of items to skip.")]


class Page[T](BaseModel):
    """One page of results plus what a client needs to request the next one."""

    items: list[T]
    total: int
    limit: int
    offset: int
