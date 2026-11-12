"""Security events: every sign-in outcome is recorded, append-only, without secrets;
users read their own history, Super Admins read everyone's."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SecurityEvent, SecurityEventType
from app.security.security_events import account_hash
from tests.factories import DEFAULT_PASSWORD, auth_headers, create_user

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ACTIVITY = "/api/v1/auth/activity"
EVENTS = "/api/v1/security-events"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Test/1.0"}


def _events(db: Session) -> list[SecurityEvent]:
    return list(db.scalars(select(SecurityEvent).order_by(SecurityEvent.id)))


def _login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD):  # noqa: ANN202
    return client.post(LOGIN, json={"email": email, "password": password}, headers=UA)


def test_registration_login_failure_and_logout_are_recorded(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        REGISTER,
        json={"email": "ada@acme.example", "password": DEFAULT_PASSWORD, "full_name": "Ada"},
        headers=UA,
    )
    user_id = response.json()["id"]
    assert _login(client, "ada@acme.example", "wrong-password-x").status_code == 401
    token = _login(client, "ada@acme.example").json()["access_token"]
    client.post(LOGOUT, headers={"Authorization": f"Bearer {token}", **UA})

    events = _events(db_session)
    assert [(e.event, e.reason) for e in events] == [
        (SecurityEventType.REGISTERED, None),
        (SecurityEventType.LOGIN_FAILED, "wrong_password"),
        (SecurityEventType.LOGIN_SUCCEEDED, None),
        (SecurityEventType.LOGOUT, None),
    ]
    assert {str(e.user_id) for e in events} == {user_id}
    assert all(e.client_ip == "testclient" for e in events)
    assert all(e.user_agent == UA["User-Agent"] for e in events)
    assert all(e.request_id for e in events)


def test_unknown_email_failures_store_a_hash_not_the_email(
    client: TestClient, db_session: Session
) -> None:
    _login(client, "Stranger@Acme.Example", "wrong-password-x")
    (event,) = _events(db_session)
    assert event.event == SecurityEventType.LOGIN_FAILED
    assert event.reason == "unknown_email"
    assert event.user_id is None
    assert event.account_hash == account_hash("stranger@acme.example")
    row = db_session.execute(text("SELECT row_to_json(e)::text FROM security_events e")).scalar()
    assert "stranger" not in row.lower()


def test_no_passwords_or_tokens_are_stored(client: TestClient, db_session: Session) -> None:
    create_user(db_session, email="secret@acme.example")
    _login(client, "secret@acme.example", "wrong-password-x")
    token = _login(client, "secret@acme.example").json()["access_token"]
    rows = db_session.execute(text("SELECT row_to_json(e)::text FROM security_events e")).scalars()
    dump = " ".join(rows)
    assert DEFAULT_PASSWORD not in dump
    assert "wrong-password-x" not in dump
    assert token not in dump


def test_a_rate_limit_refusal_is_recorded_once_per_window(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "auth_login_failures_limit", 2)
    create_user(db_session, email="locked@acme.example")
    statuses = [_login(client, "locked@acme.example", "wrong-x-pass").status_code for _ in range(6)]
    assert statuses == [401, 401, 429, 429, 429, 429]

    limited = [e for e in _events(db_session) if e.event == SecurityEventType.LOGIN_RATE_LIMITED]
    assert len(limited) == 1
    assert limited[0].reason == "login_failures"


def test_events_cannot_be_changed_or_deleted(client: TestClient, db_session: Session) -> None:
    _login(client, "nobody@acme.example", "wrong-password-x")
    for statement in (
        "UPDATE security_events SET reason = 'edited'",
        "DELETE FROM security_events",
    ):
        with pytest.raises(DBAPIError, match="append-only"), db_session.begin_nested():
            db_session.execute(text(statement))


def test_users_see_only_their_own_activity(client: TestClient, db_session: Session) -> None:
    ada = create_user(db_session, email="ada2@acme.example")
    bob = create_user(db_session, email="bob2@acme.example")
    _login(client, ada.email, "wrong-password-x")
    _login(client, ada.email)
    _login(client, bob.email)

    response = client.get(ACTIVITY, headers=auth_headers(ada))
    assert response.status_code == 200
    body = response.json()
    assert [e["event"] for e in body] == ["login_succeeded", "login_failed"]  # newest first
    assert set(body[0]) == {"id", "event", "reason", "client_ip", "user_agent", "created_at"}

    limited = client.get(ACTIVITY, params={"limit": 1}, headers=auth_headers(ada)).json()
    assert len(limited) == 1
    assert client.get(ACTIVITY).status_code == 401


def test_only_super_admins_read_platform_events(client: TestClient, db_session: Session) -> None:
    member = create_user(db_session, email="member@acme.example")
    root = create_user(db_session, email="root@acme.example", is_superadmin=True)
    _login(client, "nobody@acme.example", "wrong-password-x")
    _login(client, member.email)

    refused = client.get(EVENTS, headers=auth_headers(member))
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "superadmin_required"

    page = client.get(EVENTS, headers=auth_headers(root)).json()
    assert page["total"] == 2
    assert {"user_id", "account_hash", "request_id"} <= set(page["items"][0])

    failed = client.get(EVENTS, params={"event": "login_failed"}, headers=auth_headers(root))
    assert [e["reason"] for e in failed.json()["items"]] == ["unknown_email"]
    mine = client.get(EVENTS, params={"user_id": str(member.id)}, headers=auth_headers(root))
    assert mine.json()["total"] == 1


def test_a_retention_job_may_delete_when_it_says_so(
    client: TestClient, db_session: Session
) -> None:
    _login(client, "nobody@acme.example", "wrong-password-x")
    with db_session.begin_nested():
        db_session.execute(text("SET LOCAL syncforge.allow_security_event_delete = 'on'"))
        deleted = db_session.execute(text("DELETE FROM security_events")).rowcount
    assert deleted == 1
