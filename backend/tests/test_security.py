"""Unit tests for password hashing, JWT creation/validation and secret configuration."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import PLACEHOLDER_JWT_SECRET, Settings, get_settings
from app.core.errors import AuthenticationError
from app.security.passwords import hash_password, verify_password
from app.security.tokens import create_access_token, decode_access_token


def _claims(**overrides: object) -> dict[str, object]:
    settings = get_settings()
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "type": "access",
    }
    claims.update(overrides)
    return claims


def _sign(claims: dict[str, object], secret: str | None = None) -> str:
    key = secret or get_settings().jwt_secret_key.get_secret_value()
    return jwt.encode(claims, key, algorithm="HS256")


# ---- passwords -------------------------------------------------------------------


def test_password_hash_is_argon2id_and_salted() -> None:
    first = hash_password("correct-horse-battery")
    second = hash_password("correct-horse-battery")

    assert first.startswith("$argon2id$")
    assert first != second  # random salt per hash
    assert "correct-horse-battery" not in first


def test_verify_password_accepts_correct_and_rejects_wrong_password() -> None:
    stored = hash_password("correct-horse-battery")

    assert verify_password("correct-horse-battery", stored)[0] is True
    assert verify_password("wrong-horse-battery", stored)[0] is False


# ---- tokens ----------------------------------------------------------------------


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    issued = create_access_token(user_id)

    claims = decode_access_token(issued.token)

    assert claims.user_id == user_id
    assert claims.jti == issued.jti
    assert issued.expires_in == get_settings().access_token_expire_minutes * 60


def test_each_token_gets_a_unique_jti() -> None:
    user_id = uuid.uuid4()

    assert create_access_token(user_id).jti != create_access_token(user_id).jti


def test_expired_token_is_rejected() -> None:
    expired = create_access_token(uuid.uuid4(), expires_delta=timedelta(seconds=-1))

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(expired.token)
    assert exc_info.value.code == "token_expired"


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("not-a-jwt", id="garbage"),
        pytest.param(_sign(_claims(), secret="x" * 40), id="wrong-signing-key"),
        pytest.param(_sign(_claims(aud="another-service")), id="wrong-audience"),
        pytest.param(_sign(_claims(iss="someone-else")), id="wrong-issuer"),
        pytest.param(_sign(_claims(type="refresh")), id="wrong-token-type"),
        pytest.param(_sign(_claims(sub="not-a-uuid")), id="malformed-subject"),
        pytest.param(
            _sign({k: v for k, v in _claims().items() if k != "jti"}), id="missing-jti-claim"
        ),
        pytest.param(jwt.encode(_claims(), key=None, algorithm="none"), id="alg-none-unsigned"),
    ],
)
def test_invalid_tokens_are_rejected(token: str) -> None:
    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token)
    assert exc_info.value.code == "invalid_token"


# ---- configuration ---------------------------------------------------------------


def test_short_jwt_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(jwt_secret_key="too-short")


def test_placeholder_jwt_secret_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            app_env="production",
            jwt_secret_key=PLACEHOLDER_JWT_SECRET,
            postgres_password="a-real-production-password",
        )


def test_placeholder_jwt_secret_is_allowed_in_development() -> None:
    settings = Settings(app_env="development", jwt_secret_key=PLACEHOLDER_JWT_SECRET)

    assert settings.jwt_secret_key.get_secret_value() == PLACEHOLDER_JWT_SECRET
