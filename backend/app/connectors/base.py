"""The connector interface (adapter pattern).

SyncForge's core (workflows, workers) only ever talks to `Connector`. Each external
application gets one adapter class that translates these five operations into that
application's API. Adding an application means adding one adapter and registering
it - nothing in the core changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.connectors.http import ConnectorHttpClient


@dataclass(frozen=True)
class UserProfile:
    """What SyncForge sends to an external application about one employee."""

    employee_number: str
    email: str
    first_name: str
    last_name: str
    active: bool = True
    department: str | None = None
    designation: str | None = None
    location: str | None = None

    def __repr__(self) -> str:
        return f"UserProfile(employee_number={self.employee_number!r})"  # no PII in logs


@dataclass(frozen=True)
class ExternalUser:
    """A user as the external application reports it."""

    external_id: str
    email: str
    first_name: str
    last_name: str
    active: bool
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __repr__(self) -> str:
        return f"ExternalUser(external_id={self.external_id!r}, active={self.active})"


@dataclass(frozen=True)
class ConnectionCheck:
    ok: bool
    latency_ms: float | None
    detail: str


class BaseConnectorConfig(BaseModel):
    """Non-secret settings shared by every connector type."""

    model_config = ConfigDict(extra="forbid")

    base_url: HttpUrl | None = Field(
        default=None, description="Override the default endpoint (must be an allowed host)."
    )
    rate_limit_per_minute: int | None = Field(
        default=None,
        ge=1,
        le=10000,
        description="Optional. Calls SyncForge may start per minute for this connector "
        "(shared by all workers); jobs over the limit wait for the next minute.",
    )


class BaseCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ConnectorSpec:
    connector_type: str
    display_name: str
    version: str  # semantic version of the adapter
    description: str
    auth_type: str  # e.g. "bearer_token", "oauth2_client_credentials", "api_key"
    simulated: bool  # True when the adapter talks to a local mock service
    config_model: type[BaseConnectorConfig]
    credentials_model: type[BaseCredentials]
    default_base_url_setting: str  # name of the Settings attribute with the default URL
    fingerprint_field: str  # which credential field the UI fingerprint is taken from

    @property
    def major_version(self) -> int:
        return int(self.version.split(".", 1)[0])


IDEMPOTENCY_HEADER = "Idempotency-Key"


def idempotency_headers(key: str | None) -> dict[str, str]:
    return {IDEMPOTENCY_HEADER: key} if key else {}


class Connector(ABC):
    spec: ClassVar[ConnectorSpec]

    def __init__(
        self,
        *,
        config: BaseConnectorConfig,
        credentials: BaseCredentials,
        http: ConnectorHttpClient,
    ) -> None:
        self.config = config
        self.credentials = credentials
        self.http = http

    @abstractmethod
    def test_connection(self) -> ConnectionCheck:
        """Prove the credentials work with a cheap, read-only call."""

    @abstractmethod
    def create_user(
        self, profile: UserProfile, *, idempotency_key: str | None = None
    ) -> ExternalUser:
        """Create the user. `idempotency_key` is the same for every attempt of the same
        synchronization job, so an API that honours `Idempotency-Key` creates it once
        even if an attempt timed out after the API had already acted (docs/13)."""

    @abstractmethod
    def update_user(self, external_id: str, profile: UserProfile) -> ExternalUser: ...

    @abstractmethod
    def deactivate_user(self, external_id: str) -> ExternalUser:
        """Revoke access without deleting history (suspend / deactivate)."""

    @abstractmethod
    def get_user(self, external_id: str) -> ExternalUser: ...

    def close(self) -> None:
        self.http.close()
