"""Connector core: error normalization, the HTTP client, and the registry/factory.

External APIs are simulated with httpx MockTransport here, so every status code and
network failure can be produced exactly. Real mock-service servers are used in the
adapter tests.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import ClassVar

import httpx2 as httpx
import pytest
from pydantic import SecretStr

from app.connectors import registry
from app.connectors.base import (
    BaseConnectorConfig,
    BaseCredentials,
    ConnectionCheck,
    Connector,
    ConnectorSpec,
    ExternalUser,
    UserProfile,
)
from app.connectors.errors import (
    MAX_RETRY_AFTER_SECONDS,
    ConnectorError,
    ErrorCategory,
    error_from_response,
    parse_retry_after,
)
from app.connectors.http import ConnectorHttpClient, check_allowed_url
from app.core.config import Settings

ALLOWED = ["localhost", "127.0.0.1"]


def respond(status: int, body: object = None, headers: dict[str, str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body, headers=headers)

    return httpx.MockTransport(handler)


def raising(exc_type: type[Exception]):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc_type("simulated", request=request)

    return httpx.MockTransport(handler)


def client(transport: httpx.BaseTransport) -> ConnectorHttpClient:
    return ConnectorHttpClient(
        "http://localhost:9999",
        allowed_hosts=ALLOWED,
        connect_timeout=1,
        read_timeout=1,
        transport=transport,
    )


# ---- error normalization -------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "category", "retryable"),
    [
        (400, ErrorCategory.VALIDATION, False),
        (401, ErrorCategory.AUTHENTICATION, False),
        (403, ErrorCategory.AUTHORIZATION, False),
        (404, ErrorCategory.NOT_FOUND, False),
        (409, ErrorCategory.CONFLICT, False),
        (410, ErrorCategory.PERMANENT, False),
        (422, ErrorCategory.VALIDATION, False),
        (429, ErrorCategory.RATE_LIMITED, True),
        (500, ErrorCategory.SERVER, True),
        (503, ErrorCategory.SERVER, True),
    ],
)
def test_http_status_classification(status: int, category: ErrorCategory, retryable: bool) -> None:
    with pytest.raises(ConnectorError) as caught:
        client(respond(status, {"detail": "nope"})).request("GET", "/x")

    error = caught.value
    assert (error.category, error.retryable, error.status_code) == (category, retryable, status)
    assert error.code == f"http_{status}"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"detail": "SCIM says no"}, "SCIM says no"),  # SCIM (Slack)
        ({"error": {"code": 400, "message": "Google says no"}}, "Google says no"),  # Google
        ({"message": "Payroll says no"}, "Payroll says no"),
        ({"error": "invalid_client"}, "invalid_client"),  # OAuth token endpoint
        (None, "Bad Request"),
    ],
)
def test_external_error_message_is_extracted(body: object, expected: str) -> None:
    error = error_from_response(httpx.Response(400, json=body))

    assert error.message == expected


def test_rate_limit_carries_retry_after() -> None:
    with pytest.raises(ConnectorError) as caught:
        client(respond(429, {"detail": "slow down"}, {"Retry-After": "7"})).request("GET", "/x")

    assert caught.value.retry_after == 7.0
    assert caught.value.to_dict()["retryable"] is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5", 5.0),
        ("0", 0.0),
        ("Wed, 11 Nov 2026 12:00:30 GMT", 30.0),  # HTTP-date, 30 s after "now"
        ("Wed, 11 Nov 2026 11:59:00 GMT", 0.0),  # date in the past -> retry now
        ("999999", MAX_RETRY_AFTER_SECONDS),  # capped
        ("soon", None),
        (None, None),
    ],
)
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    now = datetime(2026, 11, 11, 12, 0, 0, tzinfo=UTC)

    assert parse_retry_after(value, now=now) == expected


@pytest.mark.parametrize(
    ("exc_type", "category", "code"),
    [
        (httpx.ConnectTimeout, ErrorCategory.TIMEOUT, "connect_timeout"),
        (httpx.ReadTimeout, ErrorCategory.TIMEOUT, "read_timeout"),
        (httpx.ConnectError, ErrorCategory.NETWORK, "connect_error"),
        (httpx.RemoteProtocolError, ErrorCategory.NETWORK, "network_error"),
    ],
)
def test_transport_errors_are_normalized(
    exc_type: type[Exception], category: ErrorCategory, code: str
) -> None:
    with pytest.raises(ConnectorError) as caught:
        client(raising(exc_type)).request("GET", "/x")

    assert (caught.value.category, caught.value.code) == (category, code)
    assert caught.value.retryable is True


# ---- HTTP client ---------------------------------------------------------------------


def test_success_returns_response_and_records_latency() -> None:
    http = client(respond(200, {"ok": True}))

    assert http.request("GET", "/x").json() == {"ok": True}
    assert http.last_latency_ms is not None and http.last_latency_ms >= 0


def test_redirects_are_not_followed() -> None:
    http = client(respond(302, None, {"Location": "http://169.254.169.254/latest/meta-data"}))

    with pytest.raises(ConnectorError) as caught:
        http.request("GET", "/x")

    assert caught.value.category is ErrorCategory.PERMANENT


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://169.254.169.254", "host_not_allowed"),  # cloud metadata service
        ("http://internal-db.local:5432", "host_not_allowed"),
        ("http://user:pass@localhost:9101", "invalid_base_url"),
        ("ftp://localhost", "invalid_base_url"),
        ("localhost:9101", "invalid_base_url"),
    ],
)
def test_disallowed_urls_are_rejected_before_any_request(url: str, code: str) -> None:
    with pytest.raises(ConnectorError) as caught:
        check_allowed_url(url, ALLOWED)

    assert caught.value.category is ErrorCategory.CONFIGURATION
    assert caught.value.code == code


def test_allowed_host_matching_ignores_case() -> None:
    check_allowed_url("http://LocalHost:9101", ALLOWED)


# ---- registry and factory ------------------------------------------------------------


class EchoConfig(BaseConnectorConfig):
    region: str = "eu"


class EchoCredentials(BaseCredentials):
    api_key: SecretStr


class EchoConnector(Connector):
    """A minimal adapter used only to test the framework."""

    spec: ClassVar[ConnectorSpec] = ConnectorSpec(
        connector_type="echo-test",
        display_name="Echo (test only)",
        version="2.1.0",
        description="Test adapter.",
        auth_type="api_key",
        simulated=True,
        config_model=EchoConfig,
        credentials_model=EchoCredentials,
        default_base_url_setting="payroll_base_url",
        fingerprint_field="api_key",
    )

    def test_connection(self) -> ConnectionCheck:
        self.http.request("GET", "/ping")
        return ConnectionCheck(ok=True, latency_ms=self.http.last_latency_ms, detail="pong")

    def create_user(self, profile: UserProfile) -> ExternalUser:  # pragma: no cover
        raise NotImplementedError

    def update_user(
        self, external_id: str, profile: UserProfile
    ) -> ExternalUser:  # pragma: no cover
        raise NotImplementedError

    def deactivate_user(self, external_id: str) -> ExternalUser:  # pragma: no cover
        raise NotImplementedError

    def get_user(self, external_id: str) -> ExternalUser:  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def echo_registered() -> Iterator[None]:
    registry.register(EchoConnector)
    yield
    registry._REGISTRY.pop("echo-test", None)


SETTINGS = Settings(payroll_base_url="http://localhost:9103")


def test_build_connector_uses_default_base_url(echo_registered: None) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    connector = registry.build_connector(
        "echo-test",
        version="2.0.0",
        config={},
        credentials={"api_key": "k-1234567890"},
        settings=SETTINGS,
        transport=httpx.MockTransport(handler),
    )

    assert connector.test_connection().ok is True
    assert seen == ["http://localhost:9103/ping"]
    assert connector.credentials.api_key.get_secret_value() == "k-1234567890"


def test_base_url_override_must_be_an_allowed_host(echo_registered: None) -> None:
    with pytest.raises(ConnectorError) as caught:
        registry.build_connector(
            "echo-test",
            version="2.1.0",
            config={"base_url": "http://10.0.0.5:8080"},
            credentials={"api_key": "k-1234567890"},
            settings=SETTINGS,
        )

    assert caught.value.code == "host_not_allowed"


def test_major_version_mismatch_is_refused(echo_registered: None) -> None:
    with pytest.raises(ConnectorError) as caught:
        registry.build_connector(
            "echo-test", version="1.4.0", config={}, credentials={"api_key": "x"}, settings=SETTINGS
        )

    assert caught.value.code == "connector_version_unsupported"


def test_unknown_type_and_invalid_stored_settings(echo_registered: None) -> None:
    with pytest.raises(ConnectorError, match="Unknown connector type"):
        registry.build_connector("nope", version="1.0.0", config={}, credentials={})
    with pytest.raises(ConnectorError) as caught:
        registry.build_connector(
            "echo-test", version="2.0.0", config={}, credentials={}, settings=SETTINGS
        )
    assert caught.value.code == "invalid_settings"


def test_validate_settings_reports_fields_but_never_values(echo_registered: None) -> None:
    spec = EchoConnector.spec

    with pytest.raises(registry.ConnectorConfigurationError) as caught:
        registry.validate_settings(spec, {"region": "eu", "extra": 1}, {"api_key": "s3cr3t-value"})
    assert caught.value.errors[0]["field"] == "config.extra"

    with pytest.raises(registry.ConnectorConfigurationError) as caught:
        registry.validate_settings(spec, {}, {"wrong": "s3cr3t-value"})
    assert {e["field"] for e in caught.value.errors} == {"credentials.api_key", "credentials.wrong"}
    assert "s3cr3t-value" not in str(caught.value.errors)


def test_registering_a_different_class_under_the_same_type_fails(echo_registered: None) -> None:
    class Impostor(EchoConnector):
        pass

    with pytest.raises(ValueError, match="already registered"):
        registry.register(Impostor)
