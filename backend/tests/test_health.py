"""Tests for health/readiness probes, request IDs and the error envelope."""

import re

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.core.database import get_engine
from app.main import app, create_app


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "syncforge-api"
    assert body["version"]


def test_ready_returns_ready_when_database_is_reachable(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_ready_returns_503_when_database_is_unreachable(client: TestClient) -> None:
    # Port 1 on localhost refuses connections immediately.
    dead_engine = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none",
        connect_args={"connect_timeout": 1},
    )
    app.dependency_overrides[get_engine] = lambda: dead_engine
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides.pop(get_engine, None)
        dead_engine.dispose()

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "not_ready"
    assert error["details"] == {"database": "unreachable"}
    assert "nothing" not in response.text  # connection credentials never leak


def test_response_carries_generated_request_id(client: TestClient) -> None:
    response = client.get("/health")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_valid_incoming_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-abc.123"})

    assert response.headers["x-request-id"] == "trace-abc.123"


def test_unsafe_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "has spaces;and=symbols"})

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist", headers={"X-Request-ID": "req-404"})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "details": None,
            "request_id": "req-404",
        }
    }


def test_unhandled_exception_returns_safe_500() -> None:
    failing_app = create_app()

    @failing_app.get("/boom")
    def boom() -> None:
        raise RuntimeError("database password is hunter2")

    with TestClient(failing_app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["message"] == "An unexpected error occurred."
    assert error["request_id"] == "req-500"
    assert response.headers["x-request-id"] == "req-500"
    assert "hunter2" not in response.text
