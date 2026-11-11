"""JWT access tokens.

Claims:
  sub  user ID              jti  unique token ID (used for logout/revocation)
  iat  issued at            exp  expiry
  iss  issuer               aud  audience
  type "access"

Tokens are signed with HS256 using JWT_SECRET_KEY. Decoding pins the algorithm,
so a token with "alg": "none" or a different algorithm is always rejected.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from app.core.errors import AuthenticationError

TOKEN_TYPE = "access"  # noqa: S105 - claim value, not a secret


@dataclass(frozen=True)
class AccessToken:
    token: str
    jti: uuid.UUID
    expires_at: datetime
    expires_in: int  # seconds


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    jti: uuid.UUID
    expires_at: datetime


def create_access_token(user_id: uuid.UUID, expires_delta: timedelta | None = None) -> AccessToken:
    settings = get_settings()
    now = datetime.now(UTC)
    lifetime = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    expires_at = now + lifetime
    jti = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "jti": str(jti),
        "iat": now,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "type": TOKEN_TYPE,
    }
    token = jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return AccessToken(
        token=token,
        jti=jti,
        expires_at=expires_at,
        expires_in=int(lifetime.total_seconds()),
    )


def decode_access_token(token: str) -> TokenClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "jti", "iat", "exp", "iss", "aud", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired.", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Access token is invalid.", code="invalid_token") from exc

    if payload["type"] != TOKEN_TYPE:
        raise AuthenticationError("Access token is invalid.", code="invalid_token")
    try:
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            jti=uuid.UUID(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (ValueError, TypeError) as exc:
        raise AuthenticationError("Access token is invalid.", code="invalid_token") from exc
