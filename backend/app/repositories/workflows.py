"""Workflow, execution and integration-event data access (always organization-scoped)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Connector,
    ExecutionStatus,
    IntegrationEvent,
    IntegrationEventStatus,
    SynchronizationAttempt,
    SynchronizationJob,
    Workflow,
    WorkflowExecution,
    WorkflowStep,
)


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, organization_id: uuid.UUID, workflow_id: uuid.UUID, *, for_update: bool = False
    ) -> Workflow | None:
        query = (
            select(Workflow)
            .where(Workflow.organization_id == organization_id, Workflow.id == workflow_id)
            .options(selectinload(Workflow.steps))
        )
        if for_update:
            query = query.with_for_update(of=Workflow)
        return self.session.scalar(query)

    def name_taken(
        self, organization_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        query = select(Workflow.id).where(
            Workflow.organization_id == organization_id, Workflow.name == name
        )
        if exclude_id is not None:
            query = query.where(Workflow.id != exclude_id)
        return self.session.scalar(query) is not None

    def add(self, workflow: Workflow) -> Workflow:
        self.session.add(workflow)
        self.session.flush()
        return workflow

    def connectors(
        self, organization_id: uuid.UUID, connector_ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, Connector]:
        """The organization's connectors among `connector_ids` (others are simply absent)."""
        if not connector_ids:
            return {}
        rows = self.session.scalars(
            select(Connector).where(
                Connector.organization_id == organization_id, Connector.id.in_(connector_ids)
            )
        )
        return {connector.id: connector for connector in rows}

    def connectors_for_steps(self, workflows: list[Workflow]) -> dict[uuid.UUID, Connector]:
        ids = {step.connector_id for workflow in workflows for step in workflow.steps}
        if not ids:
            return {}
        return {
            c.id: c for c in self.session.scalars(select(Connector).where(Connector.id.in_(ids)))
        }

    def delete_steps(self, workflow: Workflow) -> None:
        """Remove every step now (before new ones reuse the same positions)."""
        workflow.steps.clear()
        self.session.flush()

    def add_steps(self, workflow: Workflow, steps: list[WorkflowStep]) -> None:
        workflow.steps.extend(steps)
        self.session.flush()

    # Defined last: inside the class body, `list` would otherwise shadow the builtin
    # in the annotations of the methods that follow it.
    def list(
        self,
        organization_id: uuid.UUID,
        *,
        trigger_event_type: str | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Workflow], int]:
        conditions = [Workflow.organization_id == organization_id]
        if trigger_event_type is not None:
            conditions.append(Workflow.trigger_event_type == trigger_event_type)
        if is_active is not None:
            conditions.append(Workflow.is_active.is_(is_active))
        total = self.session.scalar(select(func.count()).select_from(Workflow).where(*conditions))
        items = self.session.scalars(
            select(Workflow)
            .where(*conditions)
            .options(selectinload(Workflow.steps))
            .order_by(Workflow.name, Workflow.id)
            .limit(limit)
            .offset(offset)
        )
        return list(items), total or 0


@dataclass(frozen=True)
class EventFilters:
    status: IntegrationEventStatus | None = None
    event_type: str | None = None
    employee_id: uuid.UUID | None = None


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, organization_id: uuid.UUID, event_id: uuid.UUID) -> IntegrationEvent | None:
        return self.session.scalar(
            select(IntegrationEvent).where(
                IntegrationEvent.organization_id == organization_id,
                IntegrationEvent.id == event_id,
            )
        )

    def list(
        self, organization_id: uuid.UUID, filters: EventFilters, *, limit: int, offset: int
    ) -> tuple[list[IntegrationEvent], int]:
        conditions = [IntegrationEvent.organization_id == organization_id]
        if filters.status is not None:
            conditions.append(IntegrationEvent.status == filters.status)
        if filters.event_type is not None:
            conditions.append(IntegrationEvent.event_type == filters.event_type)
        if filters.employee_id is not None:
            conditions.append(IntegrationEvent.employee_id == filters.employee_id)
        total = self.session.scalar(
            select(func.count()).select_from(IntegrationEvent).where(*conditions)
        )
        items = self.session.scalars(
            select(IntegrationEvent)
            .where(*conditions)
            .order_by(IntegrationEvent.created_at.desc(), IntegrationEvent.id)
            .limit(limit)
            .offset(offset)
        )
        return list(items), total or 0


class ExecutionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def for_event(
        self, organization_id: uuid.UUID, event_id: uuid.UUID
    ) -> list[tuple[WorkflowExecution, Workflow, IntegrationEvent]]:
        rows = self.session.execute(
            self._base(organization_id)
            .where(WorkflowExecution.event_id == event_id)
            .order_by(WorkflowExecution.created_at, WorkflowExecution.id)
        )
        return [tuple(row) for row in rows]  # type: ignore[misc]

    def for_workflow(
        self,
        organization_id: uuid.UUID,
        workflow_id: uuid.UUID,
        *,
        status: ExecutionStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[WorkflowExecution, Workflow, IntegrationEvent]], int]:
        conditions = [
            WorkflowExecution.organization_id == organization_id,
            WorkflowExecution.workflow_id == workflow_id,
        ]
        if status is not None:
            conditions.append(WorkflowExecution.status == status)
        total = self.session.scalar(
            select(func.count()).select_from(WorkflowExecution).where(*conditions)
        )
        rows = self.session.execute(
            self._base(organization_id)
            .where(*conditions)
            .order_by(WorkflowExecution.created_at.desc(), WorkflowExecution.id)
            .limit(limit)
            .offset(offset)
        )
        return [tuple(row) for row in rows], total or 0  # type: ignore[misc]

    def attempts_for_event(
        self, organization_id: uuid.UUID, event_id: uuid.UUID
    ) -> list[tuple[SynchronizationAttempt, SynchronizationJob]]:
        rows = self.session.execute(
            select(SynchronizationAttempt, SynchronizationJob)
            .join(SynchronizationJob, SynchronizationJob.id == SynchronizationAttempt.job_id)
            .join(WorkflowExecution, WorkflowExecution.id == SynchronizationJob.execution_id)
            .where(
                SynchronizationAttempt.organization_id == organization_id,
                WorkflowExecution.event_id == event_id,
            )
            .order_by(
                WorkflowExecution.created_at,
                SynchronizationJob.position,
                SynchronizationAttempt.attempt_number,
            )
        )
        return [tuple(row) for row in rows]  # type: ignore[misc]

    @staticmethod
    def _base(organization_id: uuid.UUID):  # noqa: ANN205 - SQLAlchemy Select
        return (
            select(WorkflowExecution, Workflow, IntegrationEvent)
            .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
            .join(IntegrationEvent, IntegrationEvent.id == WorkflowExecution.event_id)
            .where(WorkflowExecution.organization_id == organization_id)
            .options(selectinload(WorkflowExecution.jobs))
        )
