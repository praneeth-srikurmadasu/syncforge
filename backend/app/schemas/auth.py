"""Authentication request and response schemas.

Passwords are SecretStr so they never appear in reprs, logs or error output.
Response schemas list fields explicitly - password_hash can never be serialized.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, StringConstraints

from app.models import OrganizationRole

FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

# 8 is the minimum of NIST SP 800-63B and OWASP ASVS; no composition rules (any characters,
# spaces included), so longer passphrases are easy to use.
PASSWORD_MIN_LENGTH = 8
# Upper bound stops very long inputs from being used to burn CPU in Argon2.
PASSWORD_MAX_LENGTH = 128


class RegisterRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    full_name: FullName

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "ada@acme.example",
                "password": "correct-horse-battery",
                "full_name": "Ada Lovelace",
            }
        }
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int = Field(description="Seconds until the token expires.")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    is_superadmin: bool
    created_at: datetime


class MembershipSummary(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: OrganizationRole


class MeResponse(UserResponse):
    memberships: list[MembershipSummary]
