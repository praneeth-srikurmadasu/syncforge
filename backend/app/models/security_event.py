"""Security events: sign-ins, failed sign-ins, sign-outs, registrations and refusals by
the rate limits.

These happen before an organization is chosen, so they cannot live in the
organization-scoped audit log. Append-only like `audit_logs`: no code path updates or
deletes rows, and a trigger refuses UPDATE always and DELETE unless a retention job
enables it (`SET LOCAL syncforge.allow_security_event_delete = 'on'`).

Stored: the user ID when the account is known, a SHA-256 hash of the normalized email
(so repeated attempts on one account can be grouped without storing an email someone
typed), the client IP and a shortened user agent (so people can recognize their own
sign-ins), the reason of a failure and the request ID. Never passwords or tokens.

No foreign key to users: the security history must outlive the account.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Identity, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SecurityEventType(enum.StrEnum):
    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    LOGIN_RATE_LIMITED = "login_rate_limited"
    LOGOUT = "logout"
    REGISTERED = "registered"
    REGISTRATION_RATE_LIMITED = "registration_rate_limited"


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (
        Index("ix_security_events_user_id_created_at", "user_id", "created_at"),
        Index("ix_security_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event: Mapped[SecurityEventType] = mapped_column(
        Enum(
            SecurityEventType,
            name="security_event_type",
            native_enum=False,
            create_constraint=True,
            length=30,
            values_callable=lambda members: [m.value for m in members],
        ),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column()
    account_hash: Mapped[str | None] = mapped_column(String(64))
    # e.g. wrong_password, unknown_email, inactive_user, login_ip, login_failures
    reason: Mapped[str | None] = mapped_column(String(30))
    client_ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    request_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
