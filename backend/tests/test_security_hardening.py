"""Phase 9 security controls: sign-in and registration limits, weak-password refusal,
request body size limit and security headers."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import create_superadmin
from app.core.config import get_settings
from app.models import AuthRateWindow
from app.security.password_policy import password_problem
from app.security.rate_limit import AuthRateLimiter, Rule
from tests.factories import DEFAULT_PASSWORD, create_user

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"


@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Small limits so tests reach them quickly."""
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_login_failures_limit", 3)
    monkeypatch.setattr(settings, "auth_login_ip_limit", 5)
    monkeypatch.setattr(settings, "auth_register_ip_limit", 2)
    yield


def _login(client: TestClient, email: str, password: str):  # noqa: ANN202 - httpx response
    return client.post(LOGIN, json={"email": email, "password": password})


# ---- failed logins per account ------------------------------------------------------


def test_repeated_failed_logins_block_the_account_with_retry_after(
    client: TestClient, db_session: Session, limits: None
) -> None:
    user = create_user(db_session, email="target@acme.example")

    for _ in range(3):
        assert _login(client, user.email, "wrong-password-x").status_code == 401

    # Even the correct password is refused until the window ends: guessing cannot continue.
    response = _login(client, user.email, DEFAULT_PASSWORD)
    assert response.status_code == 429
    body = response.json()["error"]
    assert body["code"] == "rate_limited"
    assert "failed sign-in attempts" in body["message"]
    seconds = int(response.headers["Retry-After"])
    assert 1 <= seconds <= get_settings().auth_login_failures_window_seconds
    assert body["details"] == {"retry_after_seconds": seconds}


def test_unknown_emails_are_limited_the_same_way(client: TestClient, limits: None) -> None:
    # Same behaviour for existing and unknown accounts: the limit reveals nothing.
    for _ in range(3):
        assert _login(client, "nobody@acme.example", "wrong-password-x").status_code == 401
    assert _login(client, "nobody@acme.example", "wrong-password-x").status_code == 429


def test_account_limit_ignores_email_case(
    client: TestClient, db_session: Session, limits: None
) -> None:
    user = create_user(db_session, email="case@acme.example")
    for email in ("case@acme.example", "CASE@acme.example", "Case@Acme.Example"):
        assert _login(client, email, "wrong-password-x").status_code == 401
    assert _login(client, user.email, DEFAULT_PASSWORD).status_code == 429


def test_successful_logins_do_not_count_as_failures(
    client: TestClient, db_session: Session, limits: None
) -> None:
    user = create_user(db_session, email="regular@acme.example")
    for _ in range(4):  # under the per-IP limit of 5
        assert _login(client, user.email, DEFAULT_PASSWORD).status_code == 200


# ---- attempts per client IP -----------------------------------------------------------


def test_many_logins_from_one_address_are_limited(
    client: TestClient, db_session: Session, limits: None
) -> None:
    users = [create_user(db_session, email=f"ip{i}@acme.example") for i in range(6)]
    statuses = [_login(client, u.email, DEFAULT_PASSWORD).status_code for u in users]
    assert statuses == [200, 200, 200, 200, 200, 429]


def test_registrations_from_one_address_are_limited(client: TestClient, limits: None) -> None:
    def register(n: int):  # noqa: ANN202
        return client.post(
            REGISTER,
            json={"email": f"new{n}@acme.example", "password": DEFAULT_PASSWORD, "full_name": "N"},
        )

    assert register(1).status_code == 201
    assert register(2).status_code == 201
    response = register(3)
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_counters_store_hashes_not_addresses_or_emails(
    client: TestClient, db_session: Session, limits: None
) -> None:
    _login(client, "private.person@acme.example", "wrong-password-x")
    keys = db_session.scalars(select(AuthRateWindow.key)).all()
    assert keys, "attempts were counted"
    for key in keys:
        rule, digest = key.split(":")
        assert rule in {"login_ip", "login_failures"}
        assert len(digest) == 64 and "private" not in key and "testclient" not in key


# ---- the limiter itself -----------------------------------------------------------------


def test_limiter_window_rolls_over(db_session: Session) -> None:
    limiter = AuthRateLimiter(db_session)
    rule = Rule("login_ip", limit=2, window_seconds=60)
    start = datetime(2026, 11, 12, 10, 0, 5, tzinfo=UTC)

    assert limiter.hit(rule, "198.51.100.7", now=start) is None
    assert limiter.hit(rule, "198.51.100.7", now=start) is None
    wait = limiter.hit(rule, "198.51.100.7", now=start)
    assert wait == pytest.approx(55)
    assert limiter.blocked(rule, "198.51.100.7", now=start) == pytest.approx(55)
    # Another subject has its own counter.
    assert limiter.hit(rule, "198.51.100.8", now=start) is None
    # The next window starts empty.
    later = start + timedelta(seconds=60)
    assert limiter.blocked(rule, "198.51.100.7", now=later) is None
    assert limiter.hit(rule, "198.51.100.7", now=later) is None


def test_old_windows_are_deleted(db_session: Session) -> None:
    limiter = AuthRateLimiter(db_session)
    rule = Rule("register_ip", limit=5, window_seconds=60)
    old = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    limiter.hit(rule, "203.0.113.1", now=old)
    limiter.hit(rule, "203.0.113.1", now=old + timedelta(days=2))
    starts = db_session.scalars(select(AuthRateWindow.window_start)).all()
    assert starts == [datetime(2026, 11, 12, 9, 0, tzinfo=UTC)]


# ---- weak passwords --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("password1", "too common"),
        ("Qwertyuiop", "too common"),
        ("aaaaaaaaaa", "single character"),
        ("my-syncforge-pass", "name of this service"),
        ("grace.hopper-2026", "email address"),
    ],
)
def test_guessable_passwords_are_refused_at_registration(
    client: TestClient, password: str, reason: str
) -> None:
    response = client.post(
        REGISTER,
        json={"email": "grace.hopper@acme.example", "password": password, "full_name": "Grace"},
    )
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert details[0]["field"] == "password"
    assert reason in details[0]["message"]
    assert password not in response.text  # the password is never echoed


def test_policy_accepts_ordinary_passphrases() -> None:
    assert password_problem("tulip-river-48", "grace.hopper@acme.example") is None
    assert password_problem("abcd1234") is not None  # on the common list
    # A short email name (under 4 characters) is not treated as a word to avoid.
    assert password_problem("blue-al-house", "al@acme.example") is None


def test_cli_refuses_common_passwords(db_session: Session) -> None:
    with pytest.raises(ValueError, match="too common"):
        create_superadmin(
            db_session, email="ops2@example.com", full_name="Ops", password="password1"
        )


# ---- request size and headers ----------------------------------------------------------


def test_declared_oversized_body_is_refused_before_the_handler(client: TestClient) -> None:
    limit = get_settings().max_request_body_bytes
    response = client.post(
        LOGIN, content=b"x" * (limit + 1), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "payload_too_large"
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_streamed_oversized_body_is_refused(client: TestClient) -> None:
    limit = get_settings().max_request_body_bytes

    def chunks() -> Iterator[bytes]:  # no Content-Length: sent chunked
        for _ in range(limit // 65536 + 2):
            yield b" " * 65536

    response = client.post(LOGIN, content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_bodies_under_the_limit_are_unaffected(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session, email="small@acme.example")
    assert _login(client, user.email, DEFAULT_PASSWORD).status_code == 200


def test_security_headers_on_api_and_other_responses(client: TestClient) -> None:
    api = client.post(LOGIN, json={"email": "x@acme.example", "password": "whatever-123"})
    assert api.headers["X-Content-Type-Options"] == "nosniff"
    assert api.headers["X-Frame-Options"] == "DENY"
    assert api.headers["Referrer-Policy"] == "no-referrer"
    assert api.headers["Cache-Control"] == "no-store"
    assert "default-src 'none'" in api.headers["Content-Security-Policy"]

    health = client.get("/health")
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    # Swagger UI and the probes are not under /api: no strict CSP that would break /docs.
    assert "Content-Security-Policy" not in health.headers
    docs = client.get("/docs")
    assert "Content-Security-Policy" not in docs.headers


# ---- CORS -------------------------------------------------------------------------------


def test_cors_preflight_allows_the_configured_origin_and_needed_headers(
    client: TestClient,
) -> None:
    origin = get_settings().cors_origins[0]
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization, if-match, idempotency-key",
        },
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    allowed = response.headers["Access-Control-Allow-Headers"].lower()
    for header in ("authorization", "if-match", "idempotency-key"):
        assert header in allowed
    # No cookies are used, so credentials are never allowed cross-origin.
    assert "Access-Control-Allow-Credentials" not in response.headers


def test_cors_ignores_other_origins(client: TestClient) -> None:
    preflight = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 400
    assert "Access-Control-Allow-Origin" not in preflight.headers

    simple = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in simple.headers


def test_cors_exposes_the_headers_clients_read(client: TestClient) -> None:
    origin = get_settings().cors_origins[0]
    response = client.get("/health", headers={"Origin": origin})
    exposed = response.headers["Access-Control-Expose-Headers"].lower()
    for header in ("x-request-id", "etag", "retry-after"):
        assert header in exposed
