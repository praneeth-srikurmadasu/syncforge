"""Authentication use cases: register, log in, log out."""

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, ConflictError
from app.models import User
from app.repositories.users import RevokedTokenRepository, UserRepository
from app.security.passwords import burn_verification_time, hash_password, verify_password
from app.security.tokens import AccessToken, TokenClaims, create_access_token

logger = logging.getLogger("syncforge.auth")

# One message for unknown email, wrong password and disabled account, so the
# login endpoint cannot be used to discover which accounts exist.
_INVALID_CREDENTIALS = "Invalid email or password."


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.revoked_tokens = RevokedTokenRepository(session)

    def register(self, *, email: str, password: str, full_name: str) -> User:
        email = email.lower()
        if self.users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists.", code="email_taken")

        user = User(email=email, full_name=full_name, password_hash=hash_password(password))
        try:
            self.users.add(user)
            self.session.commit()
        except IntegrityError as exc:
            # Two concurrent registrations with the same email: the unique
            # constraint lets exactly one win; the other gets the same 409.
            self.session.rollback()
            raise ConflictError(
                "An account with this email already exists.", code="email_taken"
            ) from exc

        logger.info("user registered", extra={"user_id": str(user.id)})
        return user

    def login(self, *, email: str, password: str) -> AccessToken:
        user = self.users.get_by_email(email)
        if user is None:
            burn_verification_time(password)
            logger.info("login failed", extra={"reason": "unknown_email"})
            raise AuthenticationError(_INVALID_CREDENTIALS, code="invalid_credentials")

        is_valid, upgraded_hash = verify_password(password, user.password_hash)
        if not is_valid or not user.is_active:
            reason = "wrong_password" if not is_valid else "inactive_user"
            logger.info("login failed", extra={"reason": reason, "user_id": str(user.id)})
            raise AuthenticationError(_INVALID_CREDENTIALS, code="invalid_credentials")

        if upgraded_hash is not None:
            user.password_hash = upgraded_hash
        user.last_login_at = datetime.now(UTC)
        self.session.commit()

        logger.info("login succeeded", extra={"user_id": str(user.id)})
        return create_access_token(user.id)

    def logout(self, claims: TokenClaims) -> None:
        self.revoked_tokens.revoke(claims.jti, claims.user_id, claims.expires_at)
        self.session.commit()
        logger.info("logout", extra={"user_id": str(claims.user_id), "jti": str(claims.jti)})
