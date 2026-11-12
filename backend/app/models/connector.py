"""Connectors (configured connections to external applications), their credentials,
and the external accounts they manage.

Credentials live in their own table: they are never loaded by list queries, are only
ever stored encrypted, and can be rotated or revoked without touching the connector.

External accounts link an employee to the user ID the external application assigned
(Slack user ID, Google user ID, payroll record ID). Email is not a stable key - people
change emails - so updates and deactivations go through this mapping.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.circuit import ConnectorCircuit


class ConnectorStatus(enum.StrEnum):
    PENDING = "pending"  # created, connection not tested yet
    CONNECTED = "connected"  # last connection test succeeded
    ERROR = "error"  # last connection test failed
    DISCONNECTED = "disconnected"  # credentials revoked by an admin


class Connector(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connectors"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        # Target of composite foreign keys (credentials now; sync jobs in Phase 5).
        UniqueConstraint("organization_id", "id"),
        Index("ix_connectors_organization_id_connector_type", "organization_id", "connector_type"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Registry key, e.g. "slack". Validated by the service against the registry.
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Adapter version this connector was configured with (semantic version).
    connector_version: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Non-secret settings (base URL, domain, ...). Secrets never go here.
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[ConnectorStatus] = mapped_column(
        Enum(
            ConnectorStatus,
            name="connector_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        nullable=False,
        server_default=ConnectorStatus.PENDING.value,
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_category: Mapped[str | None] = mapped_column(String(30))
    last_error_message: Mapped[str | None] = mapped_column(String(500))

    credential: Mapped["ConnectorCredential | None"] = relationship(
        back_populates="connector", uselist=False, cascade="all, delete-orphan"
    )
    # Read-only view of the circuit breaker row (written by app/reliability).
    circuit: Mapped["ConnectorCircuit | None"] = relationship(
        "ConnectorCircuit",
        primaryjoin="Connector.id == foreign(ConnectorCircuit.connector_id)",
        uselist=False,
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<Connector {self.id} {self.connector_type}>"


class ConnectorCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_credentials"
    __table_args__ = (
        UniqueConstraint("connector_id"),  # one credential set per connector
        ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_connector_credentials_connector_same_organization",
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    connector_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    auth_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Fernet token of the JSON credential object. Never returned by the API.
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    # Last 4 characters of the main secret, so admins can tell keys apart.
    fingerprint: Mapped[str] = mapped_column(String(20), nullable=False)

    connector: Mapped[Connector] = relationship(back_populates="credential")

    def __repr__(self) -> str:
        return f"<ConnectorCredential {self.id}>"  # never the secret


class ExternalAccountStatus(enum.StrEnum):
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


class ExternalAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_accounts"
    __table_args__ = (
        UniqueConstraint("connector_id", "employee_id"),  # one account per app per employee
        UniqueConstraint("connector_id", "external_id"),  # an external user maps to one employee
        ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_external_accounts_connector_same_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "employee_id"],
            ["employees.organization_id", "employees.id"],
            name="fk_external_accounts_employee_same_organization",
            ondelete="CASCADE",
        ),
        Index("ix_external_accounts_organization_id_employee_id", "organization_id", "employee_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    connector_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # The ID the external application assigned (opaque to SyncForge).
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ExternalAccountStatus] = mapped_column(
        Enum(
            ExternalAccountStatus,
            name="external_account_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        nullable=False,
        server_default=ExternalAccountStatus.ACTIVE.value,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<ExternalAccount {self.id}>"
