"""The dead-letter queue: events whose processing failed for good.

An event is dead-lettered when a step fails and will not be retried - the error is not
retryable (wrong credentials, invalid data, a misconfigured connector) or the retry
budget is used up. The event moves to status `dead_letter` and one entry is written
here.

The entry *copies* the error (connector, operation, category, code, HTTP status,
message, attempt count) instead of pointing at the job's current values, because a
replay resets the job: without the copy, replaying would erase the evidence of why it
failed. An event can be dead-lettered, replayed and dead-lettered again; every round
leaves its own entry, and a partial unique index allows at most one *open* entry per
event.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DeadLetterStatus(enum.StrEnum):
    OPEN = "open"  # waiting for someone to look at it
    REPLAYED = "replayed"  # an authorized user sent the event back for processing


class DeadLetterReason(enum.StrEnum):
    RETRIES_EXHAUSTED = "retries_exhausted"  # retryable, but out of attempts
    NON_RETRYABLE = "non_retryable"  # retrying would not help (auth, validation, config)


def _enum(cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [m.value for m in members],
    )


class DeadLetterEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "dead_letter_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "event_id"],
            ["integration_events.organization_id", "integration_events.id"],
            name="fk_dead_letter_events_event_same_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["synchronization_jobs.organization_id", "synchronization_jobs.id"],
            name="fk_dead_letter_events_job_same_organization",
            ondelete="CASCADE",
        ),
        # At most one open entry per event: replay closes it before the next round.
        Index(
            "uq_dead_letter_events_open_event_id",
            "event_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        # The dashboard's queue: an organization's entries by status, newest first.
        Index(
            "ix_dead_letter_events_organization_id_status_dead_lettered_at",
            "organization_id",
            "status",
            "dead_lettered_at",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reason: Mapped[DeadLetterReason] = mapped_column(
        _enum(DeadLetterReason, "dead_letter_reason"), nullable=False
    )
    # The first step that failed for good, and its error as it was at that moment.
    job_id: Mapped[uuid.UUID | None] = mapped_column()
    connector_id: Mapped[uuid.UUID | None] = mapped_column()
    operation: Mapped[str | None] = mapped_column(String(30))
    error_category: Mapped[str | None] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(50))
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(String(500))
    # Attempts the failed step made in this round (since the last replay).
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # How many steps failed for good in this round (several workflows can match).
    failed_steps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    dead_lettered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[DeadLetterStatus] = mapped_column(
        _enum(DeadLetterStatus, "dead_letter_status"),
        nullable=False,
        server_default=DeadLetterStatus.OPEN.value,
    )
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who replayed it. SET NULL: removing a user must not delete the history.
    replayed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    def __repr__(self) -> str:
        return f"<DeadLetterEvent {self.id} event={self.event_id} {self.status}>"
