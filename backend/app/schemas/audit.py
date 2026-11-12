"""Audit log schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import ActorType, AuditOutcome


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    actor_type: ActorType = Field(description="`user` (through the API) or `system` (workers)")
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: AuditOutcome
    details: dict[str, Any] = Field(
        description="IDs, changed field names, error categories. Never secrets or personal values."
    )
    request_id: str | None = Field(description="Links the entry to the API and worker logs.")
