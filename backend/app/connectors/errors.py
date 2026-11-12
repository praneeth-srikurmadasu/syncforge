"""Normalized connector errors.

Every external application fails differently (Slack returns SCIM errors, Google returns
its own JSON, payroll something else). Connectors translate all of them into one
`ConnectorError` with a `category`, so the rest of SyncForge - and the retry engine in
Phase 6 - can decide what to do without knowing which application failed.

Only some categories are worth retrying: retrying a wrong password or an invalid
payload just fails again, while a timeout, a 503 or a 429 often succeeds later.
"""

import enum
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx2 as httpx

# Upper bound for a server-provided Retry-After, so a misbehaving API cannot park a
# job for days.
MAX_RETRY_AFTER_SECONDS = 3600.0
_MAX_MESSAGE_LENGTH = 300
# Error an idempotency-aware API returns while a request with the same key is running.
IDEMPOTENCY_KEY_IN_USE = "idempotency_key_in_use"


class ErrorCategory(enum.StrEnum):
    AUTHENTICATION = "authentication"  # 401: credentials missing, wrong or expired
    AUTHORIZATION = "authorization"  # 403: valid credentials, insufficient scope
    VALIDATION = "validation"  # 400/422: the external API rejected our data
    NOT_FOUND = "not_found"  # 404: the external user does not exist
    CONFLICT = "conflict"  # 409: e.g. the user already exists
    RATE_LIMITED = "rate_limited"  # 429: slow down (see retry_after)
    TIMEOUT = "timeout"  # no response in time
    NETWORK = "network"  # connection refused, DNS failure, connection reset
    SERVER = "server"  # 5xx: the external application is failing
    # 409 "idempotency_key_in_use": an earlier attempt with the same idempotency key is
    # still being executed (e.g. it timed out on our side). Retry later to get its result.
    IN_PROGRESS = "in_progress"
    PERMANENT = "permanent"  # any other 4xx: will not succeed by retrying
    CONFIGURATION = "configuration"  # our side: bad config, disallowed host, old version


RETRYABLE_CATEGORIES = frozenset(
    {
        ErrorCategory.RATE_LIMITED,
        ErrorCategory.TIMEOUT,
        ErrorCategory.NETWORK,
        ErrorCategory.SERVER,
        ErrorCategory.IN_PROGRESS,
    }
)


@dataclass
class ConnectorError(Exception):
    category: ErrorCategory
    message: str
    code: str
    status_code: int | None = None
    retry_after: float | None = None  # seconds, when the external API says when to retry

    def __post_init__(self) -> None:
        super().__init__(self.message)

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE_CATEGORIES

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "retry_after": self.retry_after,
        }


_STATUS_CATEGORIES = {
    400: ErrorCategory.VALIDATION,
    401: ErrorCategory.AUTHENTICATION,
    403: ErrorCategory.AUTHORIZATION,
    404: ErrorCategory.NOT_FOUND,
    408: ErrorCategory.TIMEOUT,
    409: ErrorCategory.CONFLICT,
    422: ErrorCategory.VALIDATION,
    429: ErrorCategory.RATE_LIMITED,
}


def category_for_status(status_code: int) -> ErrorCategory:
    if status_code in _STATUS_CATEGORIES:
        return _STATUS_CATEGORIES[status_code]
    if status_code >= 500:
        return ErrorCategory.SERVER
    return ErrorCategory.PERMANENT


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse a Retry-After header: either delay-seconds or an HTTP date (RFC 9110)."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        seconds = float(value)
    else:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - (now or datetime.now(UTC))).total_seconds()
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)


def _external_message(response: httpx.Response) -> str:
    """A short, human-readable reason from the external API's error body."""
    try:
        body = response.json()
    except ValueError:
        body = None
    message = None
    if isinstance(body, dict):
        # SCIM uses "detail", Google uses {"error": {"message"}}, others "message"/"error".
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
        message = message or body.get("detail") or body.get("message")
        if message is None and isinstance(error, str):
            message = error
    text = str(message) if message else (response.reason_phrase or "HTTP error")
    return text[:_MAX_MESSAGE_LENGTH]


def error_from_response(response: httpx.Response) -> ConnectorError:
    status = response.status_code
    category = category_for_status(status)
    retry_after = None
    if status in (429, 503):
        retry_after = parse_retry_after(response.headers.get("Retry-After"))
    message = _external_message(response)
    code = f"http_{status}"
    if status == 409 and message == IDEMPOTENCY_KEY_IN_USE:
        category, code = ErrorCategory.IN_PROGRESS, IDEMPOTENCY_KEY_IN_USE
    return ConnectorError(
        category=category,
        message=message,
        code=code,
        status_code=status,
        retry_after=retry_after,
    )


def error_from_transport(exc: httpx.TransportError) -> ConnectorError:
    if isinstance(exc, httpx.ConnectTimeout):
        return ConnectorError(ErrorCategory.TIMEOUT, "Timed out connecting.", "connect_timeout")
    if isinstance(exc, httpx.ReadTimeout):
        return ConnectorError(
            ErrorCategory.TIMEOUT, "Timed out waiting for a response.", "read_timeout"
        )
    if isinstance(exc, httpx.TimeoutException):
        return ConnectorError(ErrorCategory.TIMEOUT, "Request timed out.", "timeout")
    if isinstance(exc, httpx.ConnectError):
        return ConnectorError(ErrorCategory.NETWORK, "Could not connect.", "connect_error")
    return ConnectorError(ErrorCategory.NETWORK, "Network error.", "network_error")
