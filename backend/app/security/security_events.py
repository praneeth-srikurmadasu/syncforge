"""Recording and reading security events (app/models/security_event.py)."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.request_context import get_request_id
from app.models import SecurityEvent, SecurityEventType

USER_AGENT_LENGTH = 200


@dataclass(frozen=True)
class ClientInfo:
    """Where a request came from, as far as the API can tell."""

    ip: str | None = None
    user_agent: str | None = None


def account_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


class SecurityEventRecorder:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        event: SecurityEventType,
        *,
        client: ClientInfo | None,
        user_id: uuid.UUID | None = None,
        email: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Add an event to the session. The caller commits (with the change it describes,
        or on its own before raising an error)."""
        client = client or ClientInfo()
        self.session.add(
            SecurityEvent(
                event=event,
                user_id=user_id,
                account_hash=account_hash(email) if email else None,
                reason=reason,
                client_ip=client.ip,
                user_agent=(client.user_agent or "")[:USER_AGENT_LENGTH] or None,
                request_id=get_request_id(),
            )
        )


@dataclass(frozen=True)
class SecurityEventFilters:
    event: SecurityEventType | None = None
    user_id: uuid.UUID | None = None
    client_ip: str | None = None
    since: datetime | None = None
    until: datetime | None = None


class SecurityEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_user(self, user_id: uuid.UUID, limit: int) -> list[SecurityEvent]:
        return list(
            self.session.scalars(
                select(SecurityEvent)
                .where(SecurityEvent.user_id == user_id)
                .order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc())
                .limit(limit)
            )
        )

    def list(
        self, filters: SecurityEventFilters, *, limit: int, offset: int
    ) -> tuple[list[SecurityEvent], int]:
        query = select(SecurityEvent)
        if filters.event is not None:
            query = query.where(SecurityEvent.event == filters.event)
        if filters.user_id is not None:
            query = query.where(SecurityEvent.user_id == filters.user_id)
        if filters.client_ip is not None:
            query = query.where(SecurityEvent.client_ip == filters.client_ip)
        if filters.since is not None:
            query = query.where(SecurityEvent.created_at >= filters.since)
        if filters.until is not None:
            query = query.where(SecurityEvent.created_at < filters.until)
        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.scalars(
            query.order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total
