"""API tests for /api/v1/auth: register, login, me, logout."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import OrganizationRole, User
from app.security.tokens import create_access_token
from tests.factories import (
    DEFAULT_PASSWORD,
    add_member,
    auth_headers,
    create_organization,
    create_user,
)

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
LOGOUT = "/api/v1/auth/logout"


def _login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> str:
    response = client.post(LOGIN, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


# ---- register ----------------------------------------------------------------------


def test_register_creates_user(client: TestClient, db_session: Session) -> None:
    response = client.post(
        REGISTER,
        json={"email": "Ada@Acme.Example", "password": DEFAULT_PASSWORD, "full_name": " Ada "},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@acme.example"  # normalised to lowercase
    assert body["full_name"] == "Ada"  # surrounding whitespace trimmed
    assert body["is_superadmin"] is False
    assert "password" not in response.text and "password_hash" not in body

    stored = db_session.get(User, body["id"])
    assert stored is not None
    assert stored.password_hash.startswith("$argon2id$")


def test_register_rejects_duplicate_email_case_insensitively(
    client: TestClient, db_session: Session
) -> None:
    create_user(db_session, email="ada@acme.example")

    response = client.post(
        REGISTER,
        json={"email": "ADA@acme.example", "password": DEFAULT_PASSWORD, "full_name": "Ada"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_register_rejects_short_password_without_echoing_it(client: TestClient) -> None:
    response = client.post(
        REGISTER, json={"email": "bob@acme.example", "password": "short-p", "full_name": "Bob"}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "password"
    assert "short-p" not in response.text


def test_register_accepts_an_eight_character_password(client: TestClient) -> None:
    response = client.post(
        REGISTER, json={"email": "eve@acme.example", "password": "eight-ch", "full_name": "Eve"}
    )

    assert response.status_code == 201


def test_register_rejects_invalid_email_and_blank_name(client: TestClient) -> None:
    response = client.post(
        REGISTER, json={"email": "not-an-email", "password": DEFAULT_PASSWORD, "full_name": "  "}
    )

    assert response.status_code == 422
    fields = {detail["field"] for detail in response.json()["error"]["details"]}
    assert fields == {"email", "full_name"}


# ---- login -------------------------------------------------------------------------


def test_login_returns_bearer_token(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session, email="carol@acme.example")

    response = client.post(
        LOGIN, json={"email": "Carol@Acme.Example", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    db_session.refresh(user)
    assert user.last_login_at is not None


def test_login_failures_are_indistinguishable(client: TestClient, db_session: Session) -> None:
    create_user(db_session, email="dave@acme.example")
    create_user(db_session, email="erin@acme.example", is_active=False)

    wrong_password = client.post(
        LOGIN, json={"email": "dave@acme.example", "password": "wrong-password-123"}
    )
    unknown_email = client.post(
        LOGIN, json={"email": "nobody@acme.example", "password": DEFAULT_PASSWORD}
    )
    inactive_user = client.post(
        LOGIN, json={"email": "erin@acme.example", "password": DEFAULT_PASSWORD}
    )

    for response in (wrong_password, unknown_email, inactive_user):
        assert response.status_code == 401
        error = response.json()["error"]
        assert error["code"] == "invalid_credentials"
        assert error["message"] == "Invalid email or password."


# ---- me ----------------------------------------------------------------------------


def test_me_returns_user_and_memberships(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session, email="frank@acme.example", full_name="Frank")
    org = create_organization(db_session, name="Acme Corp", slug="acme")
    add_member(db_session, user, org, OrganizationRole.INTEGRATION_MANAGER)
    token = _login(client, "frank@acme.example")

    response = client.get(ME, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "frank@acme.example"
    assert body["memberships"] == [
        {
            "organization_id": str(org.id),
            "organization_name": "Acme Corp",
            "organization_slug": "acme",
            "role": "integration_manager",
        }
    ]


def test_me_without_token_returns_401_with_bearer_challenge(client: TestClient) -> None:
    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_with_non_bearer_scheme_returns_401(client: TestClient) -> None:
    response = client.get(ME, headers={"Authorization": "Basic dXNlcjpwYXNz"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_with_malformed_token_returns_401(client: TestClient) -> None:
    response = client.get(ME, headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_me_with_expired_token_returns_401(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session)
    expired = create_access_token(user.id, expires_delta=timedelta(seconds=-1))

    response = client.get(ME, headers={"Authorization": f"Bearer {expired.token}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_token_of_deactivated_user_is_rejected(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session)
    headers = auth_headers(user)
    user.is_active = False
    db_session.flush()

    response = client.get(ME, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


# ---- logout ------------------------------------------------------------------------


def test_logout_revokes_the_token(client: TestClient, db_session: Session) -> None:
    create_user(db_session, email="grace@acme.example")
    headers = {"Authorization": f"Bearer {_login(client, 'grace@acme.example')}"}
    assert client.get(ME, headers=headers).status_code == 200

    logout = client.post(LOGOUT, headers=headers)
    after_logout = client.get(ME, headers=headers)
    second_logout = client.post(LOGOUT, headers=headers)

    assert logout.status_code == 204
    assert after_logout.status_code == 401
    assert after_logout.json()["error"]["code"] == "token_revoked"
    assert second_logout.status_code == 401


def test_logout_only_revokes_that_one_token(client: TestClient, db_session: Session) -> None:
    create_user(db_session, email="heidi@acme.example")
    laptop = {"Authorization": f"Bearer {_login(client, 'heidi@acme.example')}"}
    phone = {"Authorization": f"Bearer {_login(client, 'heidi@acme.example')}"}

    client.post(LOGOUT, headers=laptop)

    assert client.get(ME, headers=laptop).status_code == 401
    assert client.get(ME, headers=phone).status_code == 200


def test_logout_requires_authentication(client: TestClient) -> None:
    assert client.post(LOGOUT).status_code == 401
