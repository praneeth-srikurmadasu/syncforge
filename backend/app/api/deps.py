"""Shared FastAPI dependencies: database session and the authenticated user."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AuthenticationError
from app.models import User
from app.repositories.users import RevokedTokenRepository, UserRepository
from app.security.tokens import TokenClaims, decode_access_token

DbSession = Annotated[Session, Depends(get_db)]

# auto_error=False: we raise our own AuthenticationError so a missing token gets the
# standard error envelope (and a 401, not FastAPI's default 403).
_bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access_token from login.")


@dataclass(frozen=True)
class AuthContext:
    user: User
    claims: TokenClaims


def get_auth_context(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> AuthContext:
    """Validate the bearer token on every protected request.

    Checks, in order: token present -> signature/expiry/claims valid ->
    not revoked by logout -> user still exists and is active.
    """
    if credentials is None:
        raise AuthenticationError("Authentication required.", code="not_authenticated")

    claims = decode_access_token(credentials.credentials)

    if RevokedTokenRepository(db).is_revoked(claims.jti):
        raise AuthenticationError("Access token has been revoked.", code="token_revoked")

    user = UserRepository(db).get(claims.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Access token is invalid.", code="invalid_token")

    return AuthContext(user=user, claims=claims)


def get_current_user(context: Annotated[AuthContext, Depends(get_auth_context)]) -> User:
    return context.user


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]
CurrentUser = Annotated[User, Depends(get_current_user)]
