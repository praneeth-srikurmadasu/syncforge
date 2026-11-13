"""Heartbeats of background processes (Celery workers, the outbox relay).

Each process upserts its own row every HEARTBEAT_INTERVAL_SECONDS. The API reads them to
report whether background processing is alive (GET /api/v1/system/status) without making
its own readiness depend on those processes: events wait safely in the outbox while a
worker is down. Rows of processes not seen for a day are deleted by later heartbeats.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ComponentHeartbeat(Base):
    __tablename__ = "component_heartbeats"

    # "worker" or "relay"
    component: Mapped[str] = mapped_column(String(20), primary_key=True)
    # host:pid - one row per running process
    instance: Mapped[str] = mapped_column(String(200), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
