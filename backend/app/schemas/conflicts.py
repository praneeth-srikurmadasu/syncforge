"""Data integrity schemas: policies, reconciliation results, conflicts, resolutions."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    ConflictSeverity,
    ConflictStatus,
    PolicySource,
    ResolutionKind,
    ResolutionMode,
)

ConflictField = Literal[
    "first_name", "last_name", "email", "department", "designation", "location", "account_active"
]


class PolicyResponse(BaseModel):
    field: ConflictField
    source: PolicySource = Field(
        description="`syncforge`: the employee record (fed by HR) is right. `connector`: the "
        "named connector's application is right."
    )
    connector_id: uuid.UUID | None
    resolution_mode: ResolutionMode = Field(
        description="`manual`: a person decides. `auto`: the authoritative value is applied "
        "as soon as a difference is found."
    )
    severity: ConflictSeverity
    configured: bool = Field(description="False: the built-in default applies.")


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: PolicySource
    connector_id: uuid.UUID | None = None
    resolution_mode: ResolutionMode = ResolutionMode.MANUAL
    severity: ConflictSeverity


class ReconcileResponse(BaseModel):
    connector_id: uuid.UUID
    accounts_checked: int
    conflicts_opened: int
    conflicts_refreshed: int
    conflicts_closed: int = Field(description="Open conflicts whose values agree again.")
    auto_resolved: int
    errors: list[dict[str, Any]] = Field(
        description="Accounts that could not be read: employee ID, error category and code."
    )


class ResolutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    resolution: ResolutionKind
    applied_value: str | None
    against_policy: bool
    automatic: bool
    note: str | None
    resolved_by_user_id: uuid.UUID | None
    created_at: datetime


class ConflictResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    connector_id: uuid.UUID
    field: ConflictField
    syncforge_value: str | None
    external_value: str | None
    authoritative_source: PolicySource
    severity: ConflictSeverity
    status: ConflictStatus
    employee_version: int
    first_detected_at: datetime
    last_detected_at: datetime
    times_detected: int
    resolved_at: datetime | None


class ConflictDetailResponse(ConflictResponse):
    resolutions: list[ResolutionResponse]


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Literal["use_syncforge", "use_external", "dismiss"]
    note: str | None = Field(default=None, max_length=500)
    override: bool = Field(
        default=False,
        description="Required (with a note) to choose the side the policy does not name as "
        "authoritative.",
    )
