"""The outbox relay: moves events from the database to the message broker.

It runs as its own process (`python -m app.cli outbox-relay`) and loops:

1. **Publish.** Take unpublished outbox rows, oldest first, with
   `FOR UPDATE SKIP LOCKED` - several relays can run side by side without publishing the
   same row twice in parallel. Publish each event ID, then mark the row published. If the
   broker is unreachable, record the error on the row, stop this round and try again on
   the next poll: nothing is lost, the row simply stays unpublished.
2. **Recover.** Re-publish events that should have been processed by now but were not:
   `pending` or `processing` events whose lease (`locked_until`) has expired. This covers
   a worker that crashed mid-event and a message that the broker lost. A `processing`
   event whose lease expired is put back to `pending` first: its worker is presumed dead,
   and a pending event can be claimed by the next worker that receives it. (The lease is
   renewed before every step, so it only expires if a worker stops renewing it.)

A crash between "published" and "marked published" means the event is published again
on the next poll. That is fine by design: delivery is at-least-once, and the worker's
claim step makes duplicates harmless.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import IntegrationEvent, IntegrationEventStatus, OutboxEvent

logger = logging.getLogger("syncforge.relay")

# publish(event_id, correlation_id) - hands the event to the broker or raises.
Publisher = Callable[[str, str | None], None]


@dataclass(frozen=True)
class RelayResult:
    published: int = 0
    requeued: int = 0
    failed: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


class OutboxRelay:
    def __init__(
        self, session: Session, publish: Publisher, settings: Settings | None = None
    ) -> None:
        self.session = session
        self.publish = publish
        self.settings = settings or get_settings()

    def run_once(self) -> RelayResult:
        published, failed = self.publish_pending()
        requeued = 0 if failed else self.requeue_expired()
        return RelayResult(published=published, requeued=requeued, failed=failed)

    def publish_pending(self) -> tuple[int, bool]:
        """Publish one batch of unpublished outbox rows. Returns (published, broker_failed)."""
        rows = self.session.execute(
            select(OutboxEvent, IntegrationEvent)
            .join(IntegrationEvent, IntegrationEvent.id == OutboxEvent.event_id)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.id)
            .limit(self.settings.outbox_batch_size)
            .with_for_update(of=OutboxEvent, skip_locked=True)
        ).all()
        published = 0
        for row, event in rows:
            try:
                self.publish(str(event.id), event.correlation_id)
            except Exception as exc:  # broker down: keep the row, retry next poll
                row.publish_attempts += 1
                row.last_error = f"{type(exc).__name__}: {exc}"[:500]
                self.session.commit()
                logger.warning(
                    "outbox publish failed",
                    extra={"event_id": str(event.id), "error": row.last_error},
                )
                return published, True
            now = _now()
            row.published_at = now
            row.publish_attempts += 1
            row.last_error = None
            # Until a worker claims it, the event is "queued": give it one lease period
            # before the recovery step considers the message lost.
            event.locked_until = now + timedelta(seconds=self.settings.worker_lease_seconds)
            published += 1
        self.session.commit()
        if published:
            logger.info("outbox rows published", extra={"count": published})
        return published, False

    def requeue_expired(self) -> int:
        """Re-publish unfinished events whose lease expired (crashed worker, lost message)."""
        now = _now()
        events = list(
            self.session.scalars(
                select(IntegrationEvent)
                .where(
                    IntegrationEvent.status.in_(
                        [IntegrationEventStatus.PENDING, IntegrationEventStatus.PROCESSING]
                    ),
                    IntegrationEvent.locked_until < now,
                )
                .order_by(IntegrationEvent.locked_until)
                .limit(self.settings.outbox_batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        requeued = 0
        for event in events:
            try:
                self.publish(str(event.id), event.correlation_id)
            except Exception:
                break  # broker down; the next poll tries again
            was = event.status.value
            event.status = IntegrationEventStatus.PENDING
            event.locked_until = now + timedelta(seconds=self.settings.worker_lease_seconds)
            requeued += 1
            logger.warning(
                "event re-dispatched after lease expiry",
                extra={
                    "event_id": str(event.id),
                    "previous_status": was,
                    "attempts": event.attempts,
                },
            )
        self.session.commit()
        return requeued
