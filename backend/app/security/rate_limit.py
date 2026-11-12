"""Limits on sign-in and registration attempts (brute force and sign-up abuse).

Three fixed-window rules, all configurable (app/core/config.py):

* ``login_ip``       - every login attempt from one client IP;
* ``login_failures`` - failed logins for one account (normalized email), whether or not
  the account exists, so the limit does not reveal which emails are registered;
* ``register_ip``    - registrations from one client IP.

Counters live in PostgreSQL (``auth_rate_windows``), incremented atomically with
INSERT ... ON CONFLICT DO UPDATE, so every API process shares them and the API needs no
other service to let people sign in. Subjects are stored as SHA-256 hashes.

A fixed window allows up to twice the limit across a window boundary; that is acceptable
for slowing down guessing. The per-account rule lets someone who knows an email delay
that user's sign-in for one window; the window is short and the event is recorded.
"""

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import AuthRateWindow

KEEP = timedelta(days=1)  # older windows are deleted as new ones are written


class TooManyAttemptsError(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, retry_after: float) -> None:
        seconds = max(1, math.ceil(retry_after))
        super().__init__(
            message,
            details={"retry_after_seconds": seconds},
            headers={"Retry-After": str(seconds)},
        )
        self.retry_after = seconds


@dataclass(frozen=True)
class Rule:
    name: str
    limit: int
    window_seconds: int


def login_ip_rule() -> Rule:
    s = get_settings()
    return Rule("login_ip", s.auth_login_ip_limit, s.auth_login_ip_window_seconds)


def login_failures_rule() -> Rule:
    s = get_settings()
    return Rule("login_failures", s.auth_login_failures_limit, s.auth_login_failures_window_seconds)


def register_ip_rule() -> Rule:
    s = get_settings()
    return Rule("register_ip", s.auth_register_ip_limit, s.auth_register_ip_window_seconds)


def _key(rule: Rule, subject: str) -> str:
    return f"{rule.name}:{hashlib.sha256(subject.encode()).hexdigest()}"


def _window(rule: Rule, now: datetime) -> tuple[datetime, float]:
    """Start of the window containing `now`, and the seconds until it ends."""
    epoch = now.timestamp()
    start = epoch - (epoch % rule.window_seconds)
    return datetime.fromtimestamp(start, UTC), start + rule.window_seconds - epoch


class AuthRateLimiter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def hit(self, rule: Rule, subject: str, *, now: datetime | None = None) -> float | None:
        """Count one attempt. Commits, so the count survives a failed request.

        Returns None while within the limit, else the seconds until the window ends."""
        now = now or datetime.now(UTC)
        start, remaining = _window(rule, now)
        hits = self.session.execute(
            insert(AuthRateWindow)
            .values(key=_key(rule, subject), window_start=start, hits=1)
            .on_conflict_do_update(
                index_elements=["key", "window_start"],
                set_={"hits": AuthRateWindow.hits + 1},
            )
            .returning(AuthRateWindow.hits)
        ).scalar_one()
        self.session.execute(delete(AuthRateWindow).where(AuthRateWindow.window_start < now - KEEP))
        self.session.commit()
        return None if hits <= rule.limit else remaining

    def blocked(self, rule: Rule, subject: str, *, now: datetime | None = None) -> float | None:
        """Without counting: None if another attempt is allowed, else seconds to wait."""
        now = now or datetime.now(UTC)
        start, remaining = _window(rule, now)
        hits = self.session.execute(
            select(AuthRateWindow.hits).where(
                AuthRateWindow.key == _key(rule, subject), AuthRateWindow.window_start == start
            )
        ).scalar_one_or_none()
        return remaining if hits is not None and hits >= rule.limit else None
