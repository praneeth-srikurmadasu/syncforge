"""Fixed-window counters that limit sign-in and registration attempts.

`key` is "<rule>:<sha256 of the subject>" - the subject (client IP or normalized email)
is hashed, so the table holds no addresses or emails. Rows older than a day are deleted
as new ones are written (app/security/rate_limit.py).
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuthRateWindow(Base):
    __tablename__ = "auth_rate_windows"
    __table_args__ = (CheckConstraint("hits >= 0", name="hits_non_negative"),)

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, index=True
    )
    hits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
