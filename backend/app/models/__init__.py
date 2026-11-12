"""ORM models. Importing this package registers every table on Base.metadata,
which Alembic uses to compare models against the database."""

from app.models.base import Base
from app.models.connector import (
    Connector,
    ConnectorCredential,
    ConnectorStatus,
    ExternalAccount,
    ExternalAccountStatus,
)
from app.models.employee import Department, Employee, EmploymentStatus
from app.models.event import IntegrationEvent, IntegrationEventStatus, OutboxEvent
from app.models.organization import Organization, OrganizationMembership, OrganizationRole
from app.models.revoked_token import RevokedToken
from app.models.user import User
from app.models.workflow import (
    TRIGGER_EVENT_TYPES,
    ExecutionStatus,
    JobStatus,
    StepOperation,
    SynchronizationJob,
    Workflow,
    WorkflowExecution,
    WorkflowStep,
)

__all__ = [
    "TRIGGER_EVENT_TYPES",
    "Base",
    "Connector",
    "ConnectorCredential",
    "ConnectorStatus",
    "Department",
    "Employee",
    "EmploymentStatus",
    "ExecutionStatus",
    "ExternalAccount",
    "ExternalAccountStatus",
    "IntegrationEvent",
    "IntegrationEventStatus",
    "JobStatus",
    "Organization",
    "OrganizationMembership",
    "OrganizationRole",
    "OutboxEvent",
    "RevokedToken",
    "StepOperation",
    "SynchronizationJob",
    "User",
    "Workflow",
    "WorkflowExecution",
    "WorkflowStep",
]
