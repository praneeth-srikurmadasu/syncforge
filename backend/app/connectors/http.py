"""The single HTTP client every connector uses.

Centralizing outbound HTTP here means every connector gets the same:
* connect and read timeouts per request, and an operation deadline across all requests
  of one operation (Google's token call + the API call, Slack's DELETE + GET): no
  operation can hang a worker forever, however many requests it makes;
* host allowlist check (server-side request forgery protection);
* no automatic redirects (a redirect could point at a disallowed host);
* no proxy settings picked up implicitly from the environment;
* error normalization into ConnectorError;
* latency measurement.

It never logs request or response bodies or headers, which carry tokens and personal data.
"""

import time
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import httpx2 as httpx

from app.connectors.errors import (
    ConnectorError,
    ErrorCategory,
    error_from_response,
    error_from_transport,
)


def check_allowed_url(base_url: str, allowed_hosts: list[str]) -> None:
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConnectorError(
            ErrorCategory.CONFIGURATION, "Base URL must be an http(s) URL.", "invalid_base_url"
        )
    if parts.username or parts.password:
        raise ConnectorError(
            ErrorCategory.CONFIGURATION,
            "Base URL must not contain credentials.",
            "invalid_base_url",
        )
    if parts.hostname.lower() not in {host.lower() for host in allowed_hosts}:
        raise ConnectorError(
            ErrorCategory.CONFIGURATION,
            f"Host '{parts.hostname}' is not in CONNECTOR_ALLOWED_HOSTS.",
            "host_not_allowed",
        )


def _operation_timeout() -> ConnectorError:
    return ConnectorError(
        ErrorCategory.TIMEOUT,
        "The operation did not finish within its time limit.",
        "operation_timeout",
    )


class ConnectorHttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        allowed_hosts: list[str],
        connect_timeout: float,
        read_timeout: float,
        operation_timeout: float | None = None,
        headers: dict[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        check_allowed_url(base_url, allowed_hosts)
        self.base_url = base_url.rstrip("/")
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        # A client is built for one operation, so the deadline starts now.
        self.deadline = (
            time.monotonic() + operation_timeout if operation_timeout is not None else None
        )
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(read_timeout, connect=connect_timeout),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.last_latency_ms: float | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        timeout, capped = self._timeout()
        started = time.perf_counter()
        try:
            response = self._client.request(
                method,
                path,
                json=json,
                data=data,
                params=params,
                headers=headers,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            if capped:  # the operation's deadline, not this request's own timeout
                raise _operation_timeout() from exc
            raise error_from_transport(exc) from exc
        except httpx.TransportError as exc:
            raise error_from_transport(exc) from exc
        finally:
            self.last_latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.is_redirect:
            raise ConnectorError(
                ErrorCategory.PERMANENT,
                "Unexpected redirect from the external API.",
                f"http_{response.status_code}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise error_from_response(response)
        return response

    def _timeout(self) -> tuple[httpx.Timeout, bool]:
        """This request's timeout: the configured ones, cut down to what is left of the
        operation deadline. Returns (timeout, cut_down)."""
        if self.deadline is None:
            return httpx.Timeout(self.read_timeout, connect=self.connect_timeout), False
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _operation_timeout()
        read = min(self.read_timeout, remaining)
        connect = min(self.connect_timeout, remaining)
        capped = read < self.read_timeout or connect < self.connect_timeout
        return httpx.Timeout(read, connect=connect), capped

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
