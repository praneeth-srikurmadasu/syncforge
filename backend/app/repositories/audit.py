"""Read access to the audit log. There is deliberately no update or delete here: entries
are written by app/audit.py and never changed (a database trigger enforces it too)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, AuditOutcome


@dataclass(frozen=True)
class AuditFilters:
    action: str | None = None  # exact, or a prefix ending in "." (e.g. "employee.")
    resource_type: str | None = None
    resource_id: str | None = None
    actor_user_id: uuid.UUID | None = None
    outcome: AuditOutcome | None = None
    since: datetime | None = None
    until: datetime | None = None


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(
        self, organization_id: uuid.UUID, filters: AuditFilters, *, limit: int, offset: int
    ) -> tuple[list[AuditLog], int]:
        conditions = [AuditLog.organization_id == organization_id]
        if filters.action:
            if filters.action.endswith("."):
                conditions.append(AuditLog.action.startswith(filters.action, autoescape=True))
            else:
                conditions.append(AuditLog.action == filters.action)
        if filters.resource_type:
            conditions.append(AuditLog.resource_type == filters.resource_type)
        if filters.resource_id:
            conditions.append(AuditLog.resource_id == filters.resource_id)
        if filters.actor_user_id:
            conditions.append(AuditLog.actor_user_id == filters.actor_user_id)
        if filters.outcome:
            conditions.append(AuditLog.outcome == filters.outcome)
        if filters.since:
            conditions.append(AuditLog.created_at >= filters.since)
        if filters.until:
            conditions.append(AuditLog.created_at < filters.until)
        total = self.session.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
        items = self.session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.id.desc())  # newest first; id is monotonic
            .limit(limit)
            .offset(offset)
        )
        return list(items), total or 0
