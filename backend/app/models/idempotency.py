"""Idempotency records: the stored result of a create request sent with an
`Idempotency-Key` header.

A client that does not get an answer (timeout, dropped connection) cannot know whether
its POST was executed. If it sent a key, it simply sends the same request again: the
first execution stored its response here *in the same transaction* as the change it
made, so the repeat gets that response back instead of creating a second employee (and
a second onboarding run in every connected application).

Keys are scoped to (organization, user): two users cannot collide, and one user cannot
read another user's stored responses by guessing their keys. Records expire after
IDEMPOTENCY_TTL_HOURS; `python -m app.cli purge-idempotency-records` deletes expired
ones.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class IdempotencyRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", "idempotency_key"),
        Index("ix_idempotency_records_expires_at", "expires_at"),  # the purge query
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # e.g. "POST /employees": the same key on another endpoint is a client error.
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    # SHA-256 of the endpoint and the validated request body: detects a key reused for
    # a different request.
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    # The response exactly as first returned. It is the same data the caller was already
    # allowed to see, and it is deleted when the record expires.
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<IdempotencyRecord {self.endpoint} {self.response_status}>"
