"""Revoked access tokens (the logout denylist).

JWTs are stateless: once issued they stay valid until they expire. To make logout
real, the token's unique ID (jti) is stored here and every authenticated request
checks this table. Rows can be deleted once expires_at has passed, because an
expired token is rejected anyway - so the table stays small.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Indexed for the cleanup query: DELETE ... WHERE expires_at < now().
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
