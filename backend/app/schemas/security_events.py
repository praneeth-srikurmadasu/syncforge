"""Security event responses (sign-in history)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import SecurityEventType


class OwnSecurityEventResponse(BaseModel):
    """An event in the caller's own history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event: SecurityEventType
    reason: str | None
    client_ip: str | None
    user_agent: str | None
    created_at: datetime


class SecurityEventResponse(OwnSecurityEventResponse):
    """An event as Super Admins see it, including events not tied to a known account."""

    user_id: uuid.UUID | None
    account_hash: str | None
    request_id: str | None
