"""Integration events and the transactional outbox.

An *integration event* is the durable record that something happened to an employee
(employee.created, employee.terminated, ...) and of how far its processing has got. An
*outbox row* is the instruction "hand this event to the message broker". Both are
written in the same database transaction as the employee change itself, so a change is
never committed without its event, and an event never exists for a change that was
rolled back (the transactional outbox pattern - see docs/architecture.md).

Processing status lives on the event, not in the broker: Redis only carries "please
process event X". If a message is lost or delivered twice, the database still says
what has and has not been done.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IntegrationEventStatus(enum.StrEnum):
    PENDING = "pending"  # recorded, not yet picked up by a worker
    PROCESSING = "processing"  # claimed by a worker (until locked_until)
    RETRYING = "retrying"  # a step failed retryably; due again at next_attempt_at
    COMPLETED = "completed"  # every matching workflow succeeded (or none matched)
    # A step failed for good (not retryable, or out of attempts). The event waits in the
    # dead-letter queue (a dead_letter_events entry) until someone replays it.
    DEAD_LETTER = "dead_letter"


class IntegrationEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integration_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "employee_id"],
            ["employees.organization_id", "employees.id"],
            name="fk_integration_events_employee_same_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("organization_id", "id"),  # target of composite foreign keys
        Index("ix_integration_events_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_integration_events_organization_id_status", "organization_id", "status"),
        Index("ix_integration_events_employee_id", "employee_id"),
        # Small index the outbox relay uses to find events whose worker lease expired.
        Index(
            "ix_integration_events_unfinished_locked_until",
            "locked_until",
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
        # The relay's "which retries are due?" query.
        Index(
            "ix_integration_events_retrying_next_attempt_at",
            "next_attempt_at",
            postgresql_where=text("status = 'retrying'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # e.g. "employee.created" - validated against EmployeeEventType by the recorder.
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # What changed (field -> old/new). Read by workers and audits, never logged; the API
    # exposes only the changed field names.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Request ID of the API call that caused the event, so one ID links the request
    # log, the event and every worker log line.
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[IntegrationEventStatus] = mapped_column(
        Enum(
            IntegrationEventStatus,
            name="integration_event_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        nullable=False,
        server_default=IntegrationEventStatus.PENDING.value,
    )
    # How many times a worker has claimed this event (redeliveries included).
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Worker lease: while status is processing and this is in the future, the event
    # belongs to one worker. After it, the event can be reclaimed (crashed worker).
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # While status is retrying: when the earliest waiting step may be attempted again.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))

    def __repr__(self) -> str:
        return f"<IntegrationEvent {self.id} {self.event_type} {self.status}>"


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        # The relay scans only unpublished rows, oldest first.
        Index(
            "ix_outbox_events_unpublished",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    # Monotonic ID gives a cheap, stable publication order.
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integration_events.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500))

    def __repr__(self) -> str:
        return f"<OutboxEvent {self.id} event={self.event_id}>"
