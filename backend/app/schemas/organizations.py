"""Organization and membership request/response schemas."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.models import OrganizationRole

OrganizationName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
Slug = Annotated[
    str,
    StringConstraints(min_length=1, max_length=63, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$"),
]


class OrganizationCreate(BaseModel):
    name: OrganizationName
    slug: Slug | None = Field(
        default=None, description="Optional. Generated from the name when omitted."
    )

    model_config = ConfigDict(json_schema_extra={"example": {"name": "Acme Corp", "slug": "acme"}})


class OrganizationUpdate(BaseModel):
    name: OrganizationName


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    my_role: OrganizationRole | None = Field(
        default=None,
        description="The caller's role here; null for a Super Admin who is not a member.",
    )


class MemberCreate(BaseModel):
    email: EmailStr
    role: OrganizationRole


class MemberUpdate(BaseModel):
    role: OrganizationRole


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: OrganizationRole
    joined_at: datetime
