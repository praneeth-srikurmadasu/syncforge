"""Heartbeats written by background processes."""

import logging
import os
import socket
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import ComponentHeartbeat

logger = logging.getLogger("syncforge.heartbeat")

FORGET_AFTER = timedelta(days=1)


def instance_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"[:200]


def beat(
    session: Session,
    component: str,
    instance: str,
    *,
    started_at: datetime,
    now: datetime | None = None,
) -> None:
    """Record that `instance` of `component` is alive. Commits."""
    now = now or datetime.now(UTC)
    session.execute(
        insert(ComponentHeartbeat)
        .values(component=component, instance=instance, started_at=started_at, last_seen_at=now)
        .on_conflict_do_update(index_elements=["component", "instance"], set_={"last_seen_at": now})
    )
    session.execute(
        delete(ComponentHeartbeat).where(ComponentHeartbeat.last_seen_at < now - FORGET_AFTER)
    )
    session.commit()


class Heartbeat:
    """Beats on demand, at most once per interval (for loops such as the relay)."""

    def __init__(
        self,
        component: str,
        interval_seconds: float,
        session_factory: Callable[[], AbstractContextManager[Session]],
    ) -> None:
        self.component = component
        self.instance = instance_name()
        self.interval = interval_seconds
        self.session_factory = session_factory
        self.started_at = datetime.now(UTC)
        self._last: float | None = None

    def maybe_beat(self, monotonic_now: float) -> None:
        if self._last is not None and monotonic_now - self._last < self.interval:
            return
        self._last = monotonic_now
        try:
            with self.session_factory() as session:
                beat(session, self.component, self.instance, started_at=self.started_at)
        except Exception:  # a missed heartbeat must never stop the process
            logger.warning("heartbeat failed", extra={"component": self.component}, exc_info=True)


class HeartbeatThread:
    """Beats from a daemon thread (for Celery workers, whose main thread runs tasks)."""

    def __init__(self, heartbeat: Heartbeat) -> None:
        self.heartbeat = heartbeat
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"heartbeat-{heartbeat.component}", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import time

        while not self._stop.is_set():
            self.heartbeat.maybe_beat(time.monotonic())
            self._stop.wait(self.heartbeat.interval)
