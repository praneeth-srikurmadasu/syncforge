"""Workflow configuration use cases.

Rules enforced here:
* a workflow has 1-20 steps; each uses one of the organization's connectors (an ID from
  another organization behaves like an unknown ID) and the same connector + operation
  pair appears at most once;
* the name is unique per organization;
* new workflows start inactive; activation re-checks that no step uses a disconnected
  connector, so an obviously broken workflow cannot be switched on;
* changing the trigger or the steps increments `version` (executions record the version
  they ran, and copy their steps, so history is never rewritten).

Workflows are deactivated rather than deleted: their execution history stays readable.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import Connector, ConnectorStatus, Organization, Workflow, WorkflowStep
from app.repositories.workflows import WorkflowRepository
from app.schemas.workflows import StepInput

logger = logging.getLogger("syncforge.workflows")


class WorkflowService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.workflows = WorkflowRepository(session)

    def get(self, organization: Organization, workflow_id: uuid.UUID) -> Workflow:
        workflow = self.workflows.get(organization.id, workflow_id)
        if workflow is None:
            raise NotFoundError("Workflow not found.", code="workflow_not_found")
        return workflow

    def create(
        self,
        organization: Organization,
        *,
        name: str,
        description: str | None,
        trigger_event_type: str,
        steps: list[StepInput],
    ) -> Workflow:
        self._check_name(organization.id, name)
        self._check_steps(organization.id, steps)
        workflow = Workflow(
            organization_id=organization.id,
            name=name,
            description=description,
            trigger_event_type=trigger_event_type,
        )
        workflow.steps = self._build_steps(organization.id, steps)
        self._commit(lambda: self.workflows.add(workflow))
        self._log("workflow created", workflow)
        return workflow

    def update(
        self, organization: Organization, workflow_id: uuid.UUID, changes: dict[str, Any]
    ) -> Workflow:
        workflow = self._get_for_update(organization.id, workflow_id)
        if "name" in changes and changes["name"] != workflow.name:
            self._check_name(organization.id, changes["name"], exclude_id=workflow.id)
            workflow.name = changes["name"]
        if "description" in changes:
            workflow.description = changes["description"]

        definition_changed = False
        trigger = changes.get("trigger_event_type")
        if trigger is not None and trigger != workflow.trigger_event_type:
            workflow.trigger_event_type = trigger
            definition_changed = True
        if changes.get("steps") is not None:
            steps: list[StepInput] = changes["steps"]
            self._check_steps(organization.id, steps)
            current = [(s.connector_id, s.operation) for s in workflow.steps]
            if current != [(s.connector_id, s.operation.value) for s in steps]:
                self.workflows.delete_steps(workflow)
                self.workflows.add_steps(workflow, self._build_steps(organization.id, steps))
                definition_changed = True
        if definition_changed:
            workflow.version += 1
        self._commit(self.session.flush)
        self._log("workflow updated", workflow, definition_changed=definition_changed)
        return workflow

    def set_active(
        self, organization: Organization, workflow_id: uuid.UUID, *, active: bool
    ) -> Workflow:
        """Activate or deactivate. Idempotent."""
        workflow = self._get_for_update(organization.id, workflow_id)
        if active and not workflow.is_active:
            connectors = self.workflows.connectors(
                organization.id, {s.connector_id for s in workflow.steps}
            )
            disconnected = sorted(
                c.name for c in connectors.values() if c.status is ConnectorStatus.DISCONNECTED
            )
            if disconnected:
                raise ConflictError(
                    "Reconnect these connectors before activating the workflow.",
                    code="connector_disconnected",
                    details={"connectors": disconnected},
                )
        if workflow.is_active != active:
            workflow.is_active = active
            self.session.commit()
            self._log("workflow activated" if active else "workflow deactivated", workflow)
        else:
            self.session.commit()  # release the row lock
        return workflow

    # ---- helpers -----------------------------------------------------------------

    def _get_for_update(self, organization_id: uuid.UUID, workflow_id: uuid.UUID) -> Workflow:
        workflow = self.workflows.get(organization_id, workflow_id, for_update=True)
        if workflow is None:
            raise NotFoundError("Workflow not found.", code="workflow_not_found")
        return workflow

    def _check_name(
        self, organization_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None
    ) -> None:
        if self.workflows.name_taken(organization_id, name, exclude_id=exclude_id):
            raise ConflictError(
                "A workflow with this name already exists.", code="workflow_name_taken"
            )

    def _check_steps(self, organization_id: uuid.UUID, steps: list[StepInput]) -> None:
        pairs = [(s.connector_id, s.operation) for s in steps]
        duplicates = {p for p in pairs if pairs.count(p) > 1}
        if duplicates:
            raise UnprocessableError(
                "The same connector and operation can appear only once in a workflow.",
                code="duplicate_step",
                details=[
                    {"connector_id": str(c), "operation": o.value} for c, o in sorted(duplicates)
                ],
            )
        known: dict[uuid.UUID, Connector] = self.workflows.connectors(
            organization_id, {s.connector_id for s in steps}
        )
        unknown = sorted({str(s.connector_id) for s in steps if s.connector_id not in known})
        if unknown:
            # Same answer for "does not exist" and "belongs to another organization".
            raise UnprocessableError(
                "Connector not found.", code="connector_not_found", details={"ids": unknown}
            )

    @staticmethod
    def _build_steps(organization_id: uuid.UUID, steps: list[StepInput]) -> list[WorkflowStep]:
        return [
            WorkflowStep(
                organization_id=organization_id,
                position=position,
                connector_id=step.connector_id,
                operation=step.operation.value,
            )
            for position, step in enumerate(steps, start=1)
        ]

    def _commit(self, operation: Any) -> None:
        try:
            operation()
            self.session.commit()
        except IntegrityError as exc:  # a concurrent request took the name first
            self.session.rollback()
            if "uq_workflows_organization_id_name" in str(exc.orig):
                raise ConflictError(
                    "A workflow with this name already exists.", code="workflow_name_taken"
                ) from exc
            raise

    @staticmethod
    def _log(message: str, workflow: Workflow, **fields: Any) -> None:
        logger.info(
            message,
            extra={
                "organization_id": str(workflow.organization_id),
                "workflow_id": str(workflow.id),
                "trigger_event_type": workflow.trigger_event_type,
                "version": workflow.version,
                **fields,
            },
        )
