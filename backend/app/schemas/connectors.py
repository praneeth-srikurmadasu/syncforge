"""Connector request/response schemas.

Credentials are accepted on create/update but never returned: responses only say which
auth type is configured and show a 4-character fingerprint so admins can tell keys apart.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import CircuitState, ConnectorStatus, ExternalAccountStatus

ConnectorName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Operation = Literal["create_user", "update_user", "deactivate_user", "get_user"]


class ConnectorTypeResponse(BaseModel):
    connector_type: str
    display_name: str
    version: str
    description: str
    auth_type: str
    simulated: bool = Field(description="True when the adapter talks to a local mock service.")
    operations: list[str]
    config_schema: dict[str, Any]
    credentials_schema: dict[str, Any]


class ConnectorCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "connector_type": "slack",
                "name": "Slack (Acme workspace)",
                "config": {},
                "credentials": {"token": "xoxp-mock-local-token"},
            }
        },
    )

    connector_type: str = Field(min_length=1, max_length=50)
    name: ConnectorName
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any]


class ConnectorUpdate(BaseModel):
    """Rename, change settings, or rotate credentials. Sending credentials to a
    disconnected connector reconnects it."""

    model_config = ConfigDict(extra="forbid")

    name: ConnectorName | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None


class CredentialSummary(BaseModel):
    auth_type: str
    fingerprint: str = Field(description="Last 4 characters of the main secret, e.g. '...ken1'.")
    updated_at: datetime


class ConnectorErrorSummary(BaseModel):
    category: str
    message: str


class CircuitSummary(BaseModel):
    """The connector's circuit breaker (docs/12)."""

    state: CircuitState = Field(
        description="`closed`: normal. `open`: calls paused until `open_until` after "
        "repeated failures. `half_open`: one trial call is being made."
    )
    consecutive_failures: int
    open_until: datetime | None


class ConnectorResponse(BaseModel):
    id: uuid.UUID
    connector_type: str
    name: str
    version: str
    simulated: bool
    config: dict[str, Any]
    status: ConnectorStatus
    last_tested_at: datetime | None
    last_error: ConnectorErrorSummary | None
    credentials: CredentialSummary | None
    circuit: CircuitSummary
    created_at: datetime
    updated_at: datetime


class ConnectionTestResponse(BaseModel):
    ok: bool
    status: ConnectorStatus
    tested_at: datetime
    latency_ms: float | None
    detail: str | None = None
    error: dict[str, Any] | None = Field(
        default=None, description="Normalized error: category, code, retryable, retry_after."
    )


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Operation
    employee_id: uuid.UUID


class OperationResponse(BaseModel):
    operation: Operation
    connector_id: uuid.UUID
    employee_id: uuid.UUID
    external_id: str
    external_active: bool
    account_status: ExternalAccountStatus
    latency_ms: float | None


class ExternalAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    external_id: str
    status: ExternalAccountStatus
    last_synced_at: datetime | None
    created_at: datetime
