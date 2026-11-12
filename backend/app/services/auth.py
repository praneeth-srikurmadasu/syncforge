"""Authentication use cases: register, log in, log out."""

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, ConflictError
from app.models import User
from app.repositories.users import RevokedTokenRepository, UserRepository
from app.security.passwords import burn_verification_time, hash_password, verify_password
from app.security.rate_limit import (
    AuthRateLimiter,
    TooManyAttemptsError,
    login_failures_rule,
    login_ip_rule,
    register_ip_rule,
)
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
        self.limiter = AuthRateLimiter(session)

    def register(
        self, *, email: str, password: str, full_name: str, client_ip: str | None = None
    ) -> User:
        email = email.lower()
        if client_ip is not None:
            wait = self.limiter.hit(register_ip_rule(), client_ip)
            if wait is not None:
                logger.warning("registration rate limited", extra={"rule": "register_ip"})
                raise TooManyAttemptsError(
                    "Too many accounts were created from this network. Try again later.", wait
                )
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

    def login(self, *, email: str, password: str, client_ip: str | None = None) -> AccessToken:
        account = email.lower()
        # Limits are checked before any password hashing, so refused attempts cost little.
        if client_ip is not None:
            wait = self.limiter.hit(login_ip_rule(), client_ip)
            if wait is not None:
                logger.warning("login rate limited", extra={"rule": "login_ip"})
                raise TooManyAttemptsError(
                    f"Too many sign-in attempts from this network. Try again in "
                    f"{_human_wait(wait)}.",
                    wait,
                )
        wait = self.limiter.blocked(login_failures_rule(), account)
        if wait is not None:
            logger.warning("login rate limited", extra={"rule": "login_failures"})
            raise TooManyAttemptsError(
                f"Too many failed sign-in attempts for this account. Try again in "
                f"{_human_wait(wait)}.",
                wait,
            )

        user = self.users.get_by_email(account)
        if user is None:
            burn_verification_time(password)
            self.limiter.hit(login_failures_rule(), account)
            logger.info("login failed", extra={"reason": "unknown_email"})
            raise AuthenticationError(_INVALID_CREDENTIALS, code="invalid_credentials")

        is_valid, upgraded_hash = verify_password(password, user.password_hash)
        if not is_valid or not user.is_active:
            reason = "wrong_password" if not is_valid else "inactive_user"
            self.limiter.hit(login_failures_rule(), account)
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


def _human_wait(seconds: float) -> str:
    seconds = max(1, round(seconds))
    if seconds < 90:
        return f"{seconds} seconds"
    return f"{round(seconds / 60)} minutes"
