"""Workflow endpoints: /api/v1/organizations/{organization_id}/workflows/*"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, require_org_permission
from app.models import Connector, ExecutionStatus, IntegrationEvent, Workflow, WorkflowExecution
from app.repositories.workflows import ExecutionRepository, WorkflowRepository
from app.schemas.common import Limit, Offset, Page
from app.schemas.workflows import (
    ExecutionResponse,
    JobResponse,
    StepResponse,
    TriggerEventType,
    WorkflowCreate,
    WorkflowResponse,
    WorkflowUpdate,
)
from app.security.authorization import OrgContext, Permission
from app.services.workflows import WorkflowService

router = APIRouter(prefix="/organizations/{organization_id}/workflows", tags=["workflows"])

CanReadWorkflows = Annotated[OrgContext, Depends(require_org_permission(Permission.WORKFLOWS_READ))]
CanManageWorkflows = Annotated[
    OrgContext, Depends(require_org_permission(Permission.WORKFLOWS_MANAGE))
]

_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Member, but role lacks the required permission"},
    404: {"description": "Organization or workflow not found, or caller is not a member"},
}
_WRITE_ERRORS = _ERRORS | {
    409: {"description": "Workflow name already used"},
    422: {"description": "Invalid input, unknown connector, or duplicate step"},
}


def workflow_response(
    workflow: Workflow, connectors: dict[uuid.UUID, Connector]
) -> WorkflowResponse:
    return WorkflowResponse(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        trigger_event_type=workflow.trigger_event_type,
        is_active=workflow.is_active,
        version=workflow.version,
        steps=[
            StepResponse(
                position=step.position,
                connector_id=step.connector_id,
                connector_name=connectors[step.connector_id].name,
                connector_type=connectors[step.connector_id].connector_type,
                operation=step.operation,
            )
            for step in workflow.steps
        ],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def execution_response(
    execution: WorkflowExecution, workflow: Workflow, event: IntegrationEvent
) -> ExecutionResponse:
    return ExecutionResponse(
        id=execution.id,
        event_id=event.id,
        event_type=event.event_type,
        employee_id=event.employee_id,
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        workflow_version=execution.workflow_version,
        status=execution.status,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        jobs=[JobResponse.model_validate(job) for job in execution.jobs],
    )


def _one(db: DbSession, workflow: Workflow) -> WorkflowResponse:
    return workflow_response(workflow, WorkflowRepository(db).connectors_for_steps([workflow]))


@router.get("", response_model=Page[WorkflowResponse], responses=_ERRORS)
def list_workflows(
    access: CanReadWorkflows,
    db: DbSession,
    trigger_event_type: TriggerEventType | None = None,
    is_active: bool | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[WorkflowResponse]:
    repository = WorkflowRepository(db)
    workflows, total = repository.list(
        access.organization.id,
        trigger_event_type=trigger_event_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    connectors = repository.connectors_for_steps(workflows)
    return Page(
        items=[workflow_response(w, connectors) for w in workflows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_WRITE_ERRORS,
)
def create_workflow(
    payload: WorkflowCreate, access: CanManageWorkflows, db: DbSession
) -> WorkflowResponse:
    """Create a workflow. It starts **inactive**: activate it when it is ready to run."""
    workflow = WorkflowService(db).create(
        access.organization,
        name=payload.name,
        description=payload.description,
        trigger_event_type=payload.trigger_event_type,
        steps=payload.steps,
    )
    return _one(db, workflow)


@router.get("/{workflow_id}", response_model=WorkflowResponse, responses=_ERRORS)
def get_workflow(
    workflow_id: uuid.UUID, access: CanReadWorkflows, db: DbSession
) -> WorkflowResponse:
    return _one(db, WorkflowService(db).get(access.organization, workflow_id))


@router.patch("/{workflow_id}", response_model=WorkflowResponse, responses=_WRITE_ERRORS)
def update_workflow(
    workflow_id: uuid.UUID, payload: WorkflowUpdate, access: CanManageWorkflows, db: DbSession
) -> WorkflowResponse:
    """Change any field. `steps` replaces the whole list. Changing the trigger or steps
    increments `version`; executions already running or finished are not affected."""
    changes = payload.model_dump(exclude_unset=True)
    if payload.steps is not None:
        changes["steps"] = payload.steps
    workflow = WorkflowService(db).update(access.organization, workflow_id, changes)
    return _one(db, workflow)


@router.post(
    "/{workflow_id}/activate",
    response_model=WorkflowResponse,
    responses=_ERRORS | {409: {"description": "A step uses a disconnected connector"}},
)
def activate_workflow(
    workflow_id: uuid.UUID, access: CanManageWorkflows, db: DbSession
) -> WorkflowResponse:
    """Start running this workflow for new matching events. Idempotent."""
    return _one(db, WorkflowService(db).set_active(access.organization, workflow_id, active=True))


@router.post("/{workflow_id}/deactivate", response_model=WorkflowResponse, responses=_ERRORS)
def deactivate_workflow(
    workflow_id: uuid.UUID, access: CanManageWorkflows, db: DbSession
) -> WorkflowResponse:
    """Stop running this workflow for new events. History is kept. Idempotent."""
    return _one(db, WorkflowService(db).set_active(access.organization, workflow_id, active=False))


@router.get("/{workflow_id}/executions", response_model=Page[ExecutionResponse], responses=_ERRORS)
def list_executions(
    workflow_id: uuid.UUID,
    access: CanReadWorkflows,
    db: DbSession,
    execution_status: ExecutionStatus | None = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[ExecutionResponse]:
    """Execution history of this workflow, newest first, with per-step status."""
    workflow = WorkflowService(db).get(access.organization, workflow_id)
    rows, total = ExecutionRepository(db).for_workflow(
        access.organization.id, workflow.id, status=execution_status, limit=limit, offset=offset
    )
    return Page(
        items=[execution_response(*row) for row in rows], total=total, limit=limit, offset=offset
    )
