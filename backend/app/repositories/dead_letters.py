"""Data access for the dead-letter queue. Every query is scoped to one organization."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    DeadLetterEvent,
    DeadLetterStatus,
    ExecutionStatus,
    IntegrationEvent,
    Workflow,
    WorkflowExecution,
)


class DeadLetterRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, organization_id: uuid.UUID, entry_id: uuid.UUID, *, for_update: bool = False
    ) -> DeadLetterEvent | None:
        query = select(DeadLetterEvent).where(
            DeadLetterEvent.organization_id == organization_id,
            DeadLetterEvent.id == entry_id,
        )
        if for_update:
            query = query.with_for_update()
        return self.session.scalar(query)

    def event(
        self, organization_id: uuid.UUID, event_id: uuid.UUID, *, for_update: bool = False
    ) -> IntegrationEvent | None:
        query = select(IntegrationEvent).where(
            IntegrationEvent.organization_id == organization_id,
            IntegrationEvent.id == event_id,
        )
        if for_update:
            query = query.with_for_update()
        return self.session.scalar(query)

    def events(
        self, organization_id: uuid.UUID, event_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, IntegrationEvent]:
        if not event_ids:
            return {}
        rows = self.session.scalars(
            select(IntegrationEvent).where(
                IntegrationEvent.organization_id == organization_id,
                IntegrationEvent.id.in_(event_ids),
            )
        )
        return {event.id: event for event in rows}

    def failed_executions(
        self, organization_id: uuid.UUID, event_id: uuid.UUID
    ) -> list[tuple[WorkflowExecution, Workflow]]:
        rows = self.session.execute(
            select(WorkflowExecution, Workflow)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .where(
                WorkflowExecution.organization_id == organization_id,
                WorkflowExecution.event_id == event_id,
                WorkflowExecution.status == ExecutionStatus.FAILED,
            )
            .order_by(WorkflowExecution.created_at, WorkflowExecution.id)
        )
        return [tuple(row) for row in rows]  # type: ignore[misc]

    def history(self, organization_id: uuid.UUID, event_id: uuid.UUID) -> list[DeadLetterEvent]:
        """Every dead-letter round of one event, oldest first."""
        return list(
            self.session.scalars(
                select(DeadLetterEvent)
                .where(
                    DeadLetterEvent.organization_id == organization_id,
                    DeadLetterEvent.event_id == event_id,
                )
                .order_by(DeadLetterEvent.dead_lettered_at, DeadLetterEvent.id)
            )
        )

    # Defined last: inside the class body, `list` would otherwise shadow the builtin.
    def list(
        self,
        organization_id: uuid.UUID,
        *,
        status: DeadLetterStatus | None,
        connector_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DeadLetterEvent], int]:
        conditions = [DeadLetterEvent.organization_id == organization_id]
        if status is not None:
            conditions.append(DeadLetterEvent.status == status)
        if connector_id is not None:
            conditions.append(DeadLetterEvent.connector_id == connector_id)
        total = self.session.scalar(
            select(func.count()).select_from(DeadLetterEvent).where(*conditions)
        )
        items = self.session.scalars(
            select(DeadLetterEvent)
            .where(*conditions)
            .order_by(DeadLetterEvent.dead_lettered_at.desc(), DeadLetterEvent.id)
            .limit(limit)
            .offset(offset)
        )
        return list(items), total or 0
