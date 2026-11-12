"""Authentication use cases: register, log in, log out.

Every outcome is written to `security_events` (app/models/security_event.py): sign-ins,
failures with their reason, sign-outs, registrations, and refusals by the rate limits.
A refusal is recorded once per rule, subject and window (the first refused attempt);
further refusals in the same window are in the structured logs only, so an attack cannot
grow the table without bound.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import NoReturn

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, ConflictError
from app.models import SecurityEventType, User
from app.repositories.users import RevokedTokenRepository, UserRepository
from app.security.passwords import burn_verification_time, hash_password, verify_password
from app.security.rate_limit import (
    AuthRateLimiter,
    Rule,
    TooManyAttemptsError,
    login_failures_rule,
    login_ip_rule,
    register_ip_rule,
)
from app.security.security_events import ClientInfo, SecurityEventRecorder
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
        self.events = SecurityEventRecorder(session)

    def register(
        self, *, email: str, password: str, full_name: str, client: ClientInfo | None = None
    ) -> User:
        email = email.lower()
        if client is not None and client.ip is not None:
            self._enforce(
                register_ip_rule(),
                client.ip,
                SecurityEventType.REGISTRATION_RATE_LIMITED,
                client=client,
                email=email,
                message="Too many accounts were created from this network. Try again later.",
            )
        if self.users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists.", code="email_taken")

        user = User(email=email, full_name=full_name, password_hash=hash_password(password))
        try:
            self.users.add(user)
            self.events.record(SecurityEventType.REGISTERED, client=client, user_id=user.id)
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

    def login(self, *, email: str, password: str, client: ClientInfo | None = None) -> AccessToken:
        account = email.lower()
        # Limits are checked before any password hashing, so refused attempts cost little.
        if client is not None and client.ip is not None:
            self._enforce(
                login_ip_rule(),
                client.ip,
                SecurityEventType.LOGIN_RATE_LIMITED,
                client=client,
                email=account,
                message="Too many sign-in attempts from this network. Try again in {wait}.",
            )
        failures = login_failures_rule()
        if self.limiter.blocked(failures, account) is not None:
            # Counting the refused attempt too lets the first refusal of the window be
            # recognized (hits == limit + 1) and recorded once.
            self._enforce(
                failures,
                account,
                SecurityEventType.LOGIN_RATE_LIMITED,
                client=client,
                email=account,
                message="Too many failed sign-in attempts for this account. Try again in {wait}.",
            )

        user = self.users.get_by_email(account)
        if user is None:
            burn_verification_time(password)
            self._failed(account, client, reason="unknown_email")

        is_valid, upgraded_hash = verify_password(password, user.password_hash)
        if not is_valid or not user.is_active:
            reason = "wrong_password" if not is_valid else "inactive_user"
            self._failed(account, client, reason=reason, user_id=user.id)

        if upgraded_hash is not None:
            user.password_hash = upgraded_hash
        user.last_login_at = datetime.now(UTC)
        self.events.record(SecurityEventType.LOGIN_SUCCEEDED, client=client, user_id=user.id)
        self.session.commit()

        logger.info("login succeeded", extra={"user_id": str(user.id)})
        return create_access_token(user.id)

    def logout(self, claims: TokenClaims, client: ClientInfo | None = None) -> None:
        self.revoked_tokens.revoke(claims.jti, claims.user_id, claims.expires_at)
        self.events.record(SecurityEventType.LOGOUT, client=client, user_id=claims.user_id)
        self.session.commit()
        logger.info("logout", extra={"user_id": str(claims.user_id), "jti": str(claims.jti)})

    # ---- helpers ------------------------------------------------------------------------

    def _enforce(
        self,
        rule: Rule,
        subject: str,
        event: SecurityEventType,
        *,
        client: ClientInfo | None,
        email: str,
        message: str,
    ) -> None:
        """Count an attempt against `rule`; raise 429 when it is over the limit."""
        hits, remaining = self.limiter.hit_count(rule, subject)
        if hits <= rule.limit:
            return
        if hits == rule.limit + 1:
            self.events.record(event, client=client, email=email, reason=rule.name)
            self.session.commit()
        logger.warning("rate limited", extra={"rule": rule.name})
        raise TooManyAttemptsError(message.format(wait=_human_wait(remaining)), remaining)

    def _failed(
        self,
        account: str,
        client: ClientInfo | None,
        *,
        reason: str,
        user_id: uuid.UUID | None = None,
    ) -> NoReturn:
        self.limiter.hit(login_failures_rule(), account)
        self.events.record(
            SecurityEventType.LOGIN_FAILED,
            client=client,
            user_id=user_id,
            email=account,
            reason=reason,
        )
        self.session.commit()
        logger.info(
            "login failed",
            extra={"reason": reason, **({"user_id": str(user_id)} if user_id else {})},
        )
        raise AuthenticationError(_INVALID_CREDENTIALS, code="invalid_credentials")


def _human_wait(seconds: float) -> str:
    seconds = max(1, round(seconds))
    if seconds < 90:
        return f"{seconds} seconds"
    return f"{round(seconds / 60)} minutes"
