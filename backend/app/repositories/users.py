"""User and revoked-token data access."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMembership, RevokedToken, User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        # Emails are stored lowercase (enforced by a CHECK constraint).
        return self.session.scalar(select(User).where(User.email == email.lower()))

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def list_memberships(self, user_id: uuid.UUID) -> list[OrganizationMembership]:
        statement = (
            select(OrganizationMembership)
            .join(OrganizationMembership.organization)
            .where(OrganizationMembership.user_id == user_id)
            .order_by(Organization.name)
        )
        return list(self.session.scalars(statement))


class RevokedTokenRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def is_revoked(self, jti: uuid.UUID) -> bool:
        return self.session.get(RevokedToken, jti) is not None

    def revoke(self, jti: uuid.UUID, user_id: uuid.UUID, expires_at: datetime) -> None:
        # ON CONFLICT DO NOTHING: revoking an already-revoked token is a no-op,
        # which keeps logout idempotent under retries and concurrent requests.
        statement = (
            insert(RevokedToken)
            .values(jti=jti, user_id=user_id, expires_at=expires_at)
            .on_conflict_do_nothing(index_elements=[RevokedToken.jti])
        )
        self.session.execute(statement)

    def purge_expired(self, now: datetime) -> int:
        """Delete denylist rows of tokens that have expired anyway (a token past its
        `exp` is rejected by signature validation, revoked or not)."""
        result = self.session.execute(delete(RevokedToken).where(RevokedToken.expires_at <= now))
        return result.rowcount or 0
