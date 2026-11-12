"""Retry policy: when to try a failed step again, and how long to wait.

Only failures that may succeed later are retried. The connector framework classifies
every failure (docs/10); `rate_limited`, `timeout`, `network` and `server` are retryable.
Authentication, authorization, validation, not-found, conflict, permanent and
configuration failures are not: repeating the same request would fail the same way, and
hammering an API with bad credentials can get an account locked.

Delay: exponential backoff with proportional jitter, never shorter than the external
application's `Retry-After`:

    base        = min(max_delay, base_delay * 2 ** (attempt - 1))   # 2, 4, 8, 16, ... s
    jittered    = base * uniform(1 - jitter_ratio, 1 + jitter_ratio)
    delay       = min(max_delay, max(jittered, retry_after or 0))

Jitter spreads the retries of many jobs that failed together (an outage hits every
event at once), so they do not all come back in the same second and knock the
recovering service over again. A `Retry-After` larger than `max_delay` is still capped,
so one misbehaving API cannot park a job for hours; the job is retried and, if the API
still refuses, the next delay honours it again.
"""

import random
from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5  # total attempts, the first one included
    base_delay_seconds: float = 2.0
    max_delay_seconds: float = 300.0
    jitter_ratio: float = 0.2

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetryPolicy":
        return cls(
            max_attempts=settings.retry_max_attempts,
            base_delay_seconds=settings.retry_base_delay_seconds,
            max_delay_seconds=settings.retry_max_delay_seconds,
            jitter_ratio=settings.retry_jitter_ratio,
        )

    def backoff(self, attempt: int) -> float:
        """Un-jittered delay after the given (1-based) failed attempt."""
        return min(self.max_delay_seconds, self.base_delay_seconds * 2 ** (attempt - 1))

    def delay(
        self,
        attempt: int,
        *,
        retry_after: float | None = None,
        rng: random.Random | None = None,
    ) -> float:
        """Seconds to wait before the next attempt, after `attempt` attempts failed."""
        rng = rng or random.Random()  # noqa: S311 - jitter, not security
        base = self.backoff(attempt)
        jittered = base * rng.uniform(1 - self.jitter_ratio, 1 + self.jitter_ratio)
        return min(self.max_delay_seconds, max(jittered, retry_after or 0.0))


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    delay_seconds: float | None
    reason: str  # "retryable" | "not_retryable" | "attempts_exhausted"


def decide(
    policy: RetryPolicy,
    *,
    attempts_made: int,
    retryable: bool,
    retry_after: float | None = None,
    rng: random.Random | None = None,
) -> RetryDecision:
    """Retry or give up, after `attempts_made` attempts of which the last one failed."""
    if not retryable:
        return RetryDecision(retry=False, delay_seconds=None, reason="not_retryable")
    if attempts_made >= policy.max_attempts:
        return RetryDecision(retry=False, delay_seconds=None, reason="attempts_exhausted")
    delay = policy.delay(attempts_made, retry_after=retry_after, rng=rng)
    return RetryDecision(retry=True, delay_seconds=delay, reason="retryable")
