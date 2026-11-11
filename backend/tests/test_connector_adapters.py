"""Adapters against the real mock services over HTTP: lifecycle, auth, failures.

Every test runs once per connector type, which proves the framework promise: the same
five operations and the same normalized errors, whatever the external application.
"""

import socket

import pytest

from app.connectors import registry
from app.connectors.base import Connector, UserProfile
from app.connectors.errors import ConnectorError, ErrorCategory
from app.core.config import Settings
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock

TYPES = ["slack", "google_workspace", "payroll"]
WRONG_CREDENTIALS = {
    "slack": {"token": "xoxp-wrong-token-123"},
    "google_workspace": {"client_id": "syncforge-local", "client_secret": "wrong-secret-123"},
    "payroll": {"api_key": "pk_wrong_key_12345"},
}

GRACE = UserProfile(
    employee_number="E-1001",
    email="grace.hopper@acme.example",
    first_name="Grace",
    last_name="Hopper",
    department="Engineering",
    designation="Engineer",
    location="Bengaluru",
)


def build(
    connector_type: str, settings: Settings, credentials: dict[str, str] | None = None
) -> Connector:
    return registry.build_connector(
        connector_type,
        version="1.0.0",
        config={},
        credentials=credentials or MOCK_CREDENTIALS[connector_type],
        settings=settings,
    )


def queue_fault(mock: RunningMock, **fault: object) -> None:
    from mockservices.faults import FaultSpec

    mock.state.faults.append(FaultSpec(**fault))


@pytest.mark.parametrize("connector_type", TYPES)
def test_test_connection(
    connector_type: str, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    check = build(connector_type, connector_settings).test_connection()

    assert check.ok is True
    assert check.latency_ms is not None and check.latency_ms >= 0


@pytest.mark.parametrize("connector_type", TYPES)
def test_full_user_lifecycle(
    connector_type: str, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    connector = build(connector_type, connector_settings)

    created = connector.create_user(GRACE)
    assert created.external_id
    assert (created.email, created.first_name, created.active) == (GRACE.email, "Grace", True)

    fetched = connector.get_user(created.external_id)
    assert fetched.external_id == created.external_id

    promoted = UserProfile(**{**GRACE.__dict__, "designation": "Staff Engineer"})
    updated = connector.update_user(created.external_id, promoted)
    assert updated.external_id == created.external_id and updated.active is True

    deactivated = connector.deactivate_user(created.external_id)
    assert deactivated.active is False
    assert connector.get_user(created.external_id).active is False


def test_payloads_follow_each_api_shape(
    mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    slack_user = build("slack", connector_settings).create_user(GRACE)
    google_user = build("google_workspace", connector_settings).create_user(GRACE)
    payroll_user = build("payroll", connector_settings).create_user(GRACE)

    scim = mocks["slack"].state.users[slack_user.external_id]
    enterprise = scim["urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"]
    assert scim["userName"] == "grace.hopper"
    assert enterprise == {"employeeNumber": "E-1001", "department": "Engineering"}

    google = mocks["google_workspace"].state.users[google_user.external_id]
    assert google["primaryEmail"] == GRACE.email and google["suspended"] is False
    assert google["externalIds"] == [{"type": "organization", "value": "E-1001"}]

    record = mocks["payroll"].state.users[payroll_user.external_id]
    assert (record["employee_number"], record["status"]) == ("E-1001", "active")


@pytest.mark.parametrize("connector_type", TYPES)
def test_wrong_credentials_are_an_authentication_error(
    connector_type: str, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    connector = build(connector_type, connector_settings, WRONG_CREDENTIALS[connector_type])

    with pytest.raises(ConnectorError) as caught:
        connector.test_connection()

    assert caught.value.category is ErrorCategory.AUTHENTICATION
    assert caught.value.retryable is False
    # The rejected secret never appears in the error.
    assert list(WRONG_CREDENTIALS[connector_type].values())[-1] not in str(caught.value.to_dict())


@pytest.mark.parametrize("connector_type", TYPES)
def test_duplicate_user_is_a_conflict_and_unknown_user_is_not_found(
    connector_type: str, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    connector = build(connector_type, connector_settings)
    connector.create_user(GRACE)

    with pytest.raises(ConnectorError) as duplicate:
        connector.create_user(GRACE)
    with pytest.raises(ConnectorError) as missing:
        connector.get_user("does-not-exist")

    assert duplicate.value.category is ErrorCategory.CONFLICT
    assert missing.value.category is ErrorCategory.NOT_FOUND
    assert not duplicate.value.retryable and not missing.value.retryable


@pytest.mark.parametrize("connector_type", TYPES)
def test_server_errors_are_retryable(
    connector_type: str, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    queue_fault(mocks[connector_type], kind="status", status=503, count=1)
    connector = build(connector_type, connector_settings)

    with pytest.raises(ConnectorError) as caught:
        connector.create_user(GRACE)

    assert caught.value.category is ErrorCategory.SERVER
    assert caught.value.retryable is True
    # The fault was used up: the next attempt succeeds.
    assert connector.create_user(GRACE).external_id


@pytest.mark.parametrize("connector_type", TYPES)
def test_rate_limit_carries_retry_after(
    connector_type: str, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    queue_fault(mocks[connector_type], kind="rate_limit", retry_after=7, count=1)

    with pytest.raises(ConnectorError) as caught:
        build(connector_type, connector_settings).test_connection()

    assert caught.value.category is ErrorCategory.RATE_LIMITED
    assert caught.value.retry_after == 7.0
    assert caught.value.retryable is True


@pytest.mark.parametrize("connector_type", TYPES)
def test_slow_responses_time_out(
    connector_type: str, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    queue_fault(mocks[connector_type], kind="timeout", delay_seconds=2.5, count=1)

    with pytest.raises(ConnectorError) as caught:
        build(connector_type, connector_settings).test_connection()  # read timeout is 1s

    assert caught.value.category is ErrorCategory.TIMEOUT
    assert caught.value.code == "read_timeout"
    assert caught.value.retryable is True


def test_unreachable_service_is_a_network_error(connector_settings: Settings) -> None:
    with socket.socket() as sock:  # a port that was free a moment ago: nothing listens
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Windows retries a refused loopback connection for about 2 seconds before failing,
    # so a 1s connect timeout would fire first. 5s lets the refusal arrive on any OS.
    settings = connector_settings.model_copy(
        update={
            "payroll_base_url": f"http://127.0.0.1:{port}",
            "connector_connect_timeout_seconds": 5.0,
        }
    )

    with pytest.raises(ConnectorError) as caught:
        build("payroll", settings).test_connection()

    assert caught.value.category is ErrorCategory.NETWORK
    assert caught.value.retryable is True


# ---- Google OAuth token lifecycle ----------------------------------------------------


def token_requests(mock: RunningMock) -> list[dict[str, object]]:
    return [r for r in mock.state.requests if r["path"] == "/oauth2/token"]


def test_google_token_is_cached_between_calls(
    mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    connector = build("google_workspace", connector_settings)
    connector.test_connection()
    connector.create_user(GRACE)
    build("google_workspace", connector_settings).test_connection()  # new instance, same cache

    assert len(token_requests(mocks["google_workspace"])) == 1


def test_google_gets_a_new_token_when_the_old_one_expires(
    mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    from mockservices import google_workspace as google_mock

    connector = build("google_workspace", connector_settings)
    connector.test_connection()
    google_mock.tokens.clear()  # the provider expires/revokes every issued token

    connector.create_user(GRACE)  # 401 -> fresh token -> retried once -> success

    mock = mocks["google_workspace"]
    assert len(token_requests(mock)) == 2
    api_statuses = [r["status"] for r in mock.state.requests if r["path"].startswith("/admin")]
    assert api_statuses == [200, 401, 200]
