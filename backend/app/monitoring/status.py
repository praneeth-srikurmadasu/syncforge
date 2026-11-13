"""Platform status: is background processing alive and keeping up?

Read by Super Admins (GET /api/v1/system/status) and by operators investigating a
backlog. Everything is computed from PostgreSQL, the system of record: heartbeats,
the outbox, and event states across all organizations.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    ComponentHeartbeat,
    DeadLetterEvent,
    DeadLetterStatus,
    IntegrationEvent,
    IntegrationEventStatus,
    OutboxEvent,
)

COMPONENTS = ("worker", "relay")


@dataclass(frozen=True)
class ComponentInstance:
    component: str
    instance: str
    started_at: datetime
    last_seen_at: datetime
    seconds_since_seen: float
    healthy: bool


@dataclass(frozen=True)
class SystemStatus:
    generated_at: datetime
    healthy: bool
    problems: list[str]
    components: dict[str, list[ComponentInstance]]
    outbox_unpublished: int
    outbox_oldest_unpublished_seconds: float | None
    events_by_status: dict[str, int]
    events_oldest_pending_seconds: float | None
    events_stuck_processing: int
    dead_letters_open: int


def _age(now: datetime, then: datetime | None) -> float | None:
    return round((now - then).total_seconds(), 1) if then else None


def system_status(
    session: Session, settings: Settings, now: datetime | None = None
) -> SystemStatus:
    now = now or datetime.now(UTC)
    stale_after = timedelta(seconds=settings.heartbeat_stale_after_seconds)

    components: dict[str, list[ComponentInstance]] = {c: [] for c in COMPONENTS}
    for row in session.scalars(
        select(ComponentHeartbeat).order_by(
            ComponentHeartbeat.component, ComponentHeartbeat.last_seen_at.desc()
        )
    ):
        components.setdefault(row.component, []).append(
            ComponentInstance(
                component=row.component,
                instance=row.instance,
                started_at=row.started_at,
                last_seen_at=row.last_seen_at,
                seconds_since_seen=round((now - row.last_seen_at).total_seconds(), 1),
                healthy=now - row.last_seen_at <= stale_after,
            )
        )

    unpublished, oldest_unpublished = session.execute(
        select(func.count(), func.min(OutboxEvent.created_at)).where(
            OutboxEvent.published_at.is_(None)
        )
    ).one()
    by_status = {s.value: 0 for s in IntegrationEventStatus}
    for status, count in session.execute(
        select(IntegrationEvent.status, func.count()).group_by(IntegrationEvent.status)
    ):
        by_status[status.value] = count
    oldest_pending = session.scalar(
        select(func.min(IntegrationEvent.created_at)).where(
            IntegrationEvent.status == IntegrationEventStatus.PENDING
        )
    )
    # Claimed by a worker whose lease has run out: the worker died or is far too slow. The
    # relay re-sends these (docs/09); a growing number means it cannot keep up.
    stuck = session.scalar(
        select(func.count()).where(
            IntegrationEvent.status == IntegrationEventStatus.PROCESSING,
            IntegrationEvent.locked_until < now,
        )
    )
    dead_letters = session.scalar(
        select(func.count()).where(DeadLetterEvent.status == DeadLetterStatus.OPEN)
    )

    problems: list[str] = []
    for component in COMPONENTS:
        if not any(i.healthy for i in components[component]):
            problems.append(
                f"No {component} has reported in the last "
                f"{settings.heartbeat_stale_after_seconds} seconds."
            )
    if stuck:
        problems.append(f"{stuck} event(s) are past their processing lease.")

    return SystemStatus(
        generated_at=now,
        healthy=not problems,
        problems=problems,
        components=components,
        outbox_unpublished=unpublished,
        outbox_oldest_unpublished_seconds=_age(now, oldest_unpublished),
        events_by_status=by_status,
        events_oldest_pending_seconds=_age(now, oldest_pending),
        events_stuck_processing=stuck or 0,
        dead_letters_open=dead_letters or 0,
    )
