"""Workflow and workflow-execution schemas."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models import ExecutionStatus, JobStatus, StepOperation

WorkflowName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
TriggerEventType = Literal[
    "employee.created",
    "employee.updated",
    "employee.department_changed",
    "employee.manager_changed",
    "employee.terminated",
]

MAX_STEPS = 20


class StepInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: uuid.UUID
    operation: StepOperation


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "name": "Onboarding",
                "description": "Create accounts for new hires.",
                "trigger_event_type": "employee.created",
                "steps": [
                    {"connector_id": "<slack connector id>", "operation": "create_user"},
                    {"connector_id": "<google connector id>", "operation": "create_user"},
                    {"connector_id": "<payroll connector id>", "operation": "create_user"},
                ],
            }
        },
    )

    name: WorkflowName
    description: Description | None = None
    trigger_event_type: TriggerEventType
    steps: list[StepInput] = Field(
        min_length=1, max_length=MAX_STEPS, description="Run in this order (position 1 first)."
    )


class WorkflowUpdate(BaseModel):
    """Every field is optional. `steps` replaces the whole list. Changing the trigger or
    the steps increments the workflow version; executions record the version they ran."""

    model_config = ConfigDict(extra="forbid")

    name: WorkflowName | None = None
    description: Description | None = None
    trigger_event_type: TriggerEventType | None = None
    steps: list[StepInput] | None = Field(default=None, min_length=1, max_length=MAX_STEPS)


class StepResponse(BaseModel):
    position: int
    connector_id: uuid.UUID
    connector_name: str
    connector_type: str
    operation: StepOperation


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    trigger_event_type: str
    is_active: bool
    version: int
    steps: list[StepResponse]
    created_at: datetime
    updated_at: datetime


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    connector_id: uuid.UUID
    operation: StepOperation
    status: JobStatus
    attempts: int
    external_id: str | None
    error_category: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class ExecutionResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    employee_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    workflow_version: int
    status: ExecutionStatus
    started_at: datetime | None
    finished_at: datetime | None
    jobs: list[JobResponse]
