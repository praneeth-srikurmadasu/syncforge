"""Per-connector rate limit: SyncForge paces itself before the application has to.

External APIs publish limits (Slack's SCIM API, Google's Directory API per-user quotas,
a payroll vendor's contract). Hitting them means 429s, and a burst of fifty hires would
spend its retry budget on 429s. With `rate_limit_per_minute` set in a connector's
config, workers share one counter per connector per minute (a fixed window in
PostgreSQL, incremented atomically with INSERT ... ON CONFLICT DO UPDATE). A job that
would exceed the limit is not called and not failed: it is *deferred* to the next
window and does not use up any of its retry attempts - waiting for our own limit is not
a failure. 429s that still happen (the application's limit is lower, or shared with
other clients) are handled by the retry engine with Retry-After as before.

A fixed window allows a burst of up to twice the limit across a window boundary; that
is acceptable for pacing provisioning calls and far simpler than a sliding window.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Connector, ConnectorRateWindow

WINDOW = timedelta(minutes=1)
KEEP = timedelta(hours=1)  # older windows are deleted as new ones are used


def rate_limit(connector: Connector) -> int | None:
    value = (connector.config or {}).get("rate_limit_per_minute")
    return int(value) if value else None


class RateLimiter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def acquire(self, connector: Connector, *, now: datetime | None = None) -> float | None:
        """Take one call from this minute's allowance. Commits.

        Returns None if the call may go ahead, else the seconds until the next window."""
        limit = rate_limit(connector)
        if limit is None:
            return None
        now = now or datetime.now(UTC)
        window_start = now.replace(second=0, microsecond=0)
        calls = self.session.execute(
            insert(ConnectorRateWindow)
            .values(
                connector_id=connector.id,
                organization_id=connector.organization_id,
                window_start=window_start,
                calls=1,
            )
            .on_conflict_do_update(
                index_elements=["connector_id", "window_start"],
                set_={"calls": ConnectorRateWindow.calls + 1},
            )
            .returning(ConnectorRateWindow.calls)
        ).scalar_one()
        self.session.execute(
            delete(ConnectorRateWindow).where(
                ConnectorRateWindow.connector_id == connector.id,
                ConnectorRateWindow.window_start < window_start - KEEP,
            )
        )
        self.session.commit()
        if calls <= limit:
            return None
        return (window_start + WINDOW - now).total_seconds()
