"""The audit log: an append-only record of who did what, to which resource, with what
outcome.

Rows are written in the same transaction as the change they describe (so an audited
change can never commit without its entry, and a rolled-back change leaves none), by
the API on behalf of a user or by a worker on behalf of the system.

Append-only is enforced twice: the application has no code path that updates or
deletes entries (the repository only inserts and reads), and a PostgreSQL trigger
refuses UPDATE always and DELETE unless a session explicitly enables it for a
retention job (`SET LOCAL syncforge.allow_audit_delete = 'on'`).

No foreign key to organizations: the history of an organization must outlive the
organization itself (and deleting an organization must not need to delete audit rows).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditOutcome(enum.StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class ActorType(enum.StrEnum):
    USER = "user"  # an authenticated person, through the API
    SYSTEM = "system"  # a worker or the relay, acting on its own


def _enum(cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [m.value for m in members],
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        # The audit page: one organization's entries, newest first, optionally filtered.
        Index("ix_audit_logs_organization_id_created_at", "organization_id", "created_at"),
        Index(
            "ix_audit_logs_organization_id_resource",
            "organization_id",
            "resource_type",
            "resource_id",
        ),
        Index("ix_audit_logs_organization_id_action", "organization_id", "action"),
    )

    # Monotonic: a stable order (and cursor) even for entries with the same timestamp.
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(_enum(ActorType, "audit_actor_type"))
    # SET NULL: removing a user account keeps its history (the entry says "user", the ID
    # becomes unknown); the e-mail is never copied here.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # e.g. "employee.updated", "connector.disconnected", "conflict.resolved"
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[AuditOutcome] = mapped_column(
        _enum(AuditOutcome, "audit_outcome"), nullable=False
    )
    # Details: changed field names, IDs, error categories. Never secrets, never personal
    # values (names, e-mails) - see app/audit.py for what each action records.
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # The request ID of the API call (or the event's correlation ID in a worker): links
    # the entry to the logs.
    request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.id} {self.action} {self.outcome}>"
