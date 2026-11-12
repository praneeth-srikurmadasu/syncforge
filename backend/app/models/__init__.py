"""ORM models. Importing this package registers every table on Base.metadata,
which Alembic uses to compare models against the database."""

from app.models.audit import ActorType, AuditLog, AuditOutcome
from app.models.base import Base
from app.models.circuit import CircuitState, ConnectorCircuit, ConnectorRateWindow
from app.models.connector import (
    Connector,
    ConnectorCredential,
    ConnectorStatus,
    ExternalAccount,
    ExternalAccountStatus,
)
from app.models.dead_letter import DeadLetterEvent, DeadLetterReason, DeadLetterStatus
from app.models.employee import Department, Employee, EmploymentStatus
from app.models.event import IntegrationEvent, IntegrationEventStatus, OutboxEvent
from app.models.idempotency import IdempotencyRecord
from app.models.organization import Organization, OrganizationMembership, OrganizationRole
from app.models.revoked_token import RevokedToken
from app.models.user import User
from app.models.workflow import (
    TRIGGER_EVENT_TYPES,
    AttemptOutcome,
    ExecutionStatus,
    JobStatus,
    StepOperation,
    SynchronizationAttempt,
    SynchronizationJob,
    Workflow,
    WorkflowExecution,
    WorkflowStep,
)

__all__ = [
    "ActorType",
    "AuditLog",
    "AuditOutcome",
    "TRIGGER_EVENT_TYPES",
    "AttemptOutcome",
    "Base",
    "CircuitState",
    "Connector",
    "ConnectorCircuit",
    "ConnectorCredential",
    "ConnectorRateWindow",
    "ConnectorStatus",
    "DeadLetterEvent",
    "DeadLetterReason",
    "DeadLetterStatus",
    "Department",
    "Employee",
    "EmploymentStatus",
    "ExecutionStatus",
    "ExternalAccount",
    "ExternalAccountStatus",
    "IdempotencyRecord",
    "IntegrationEvent",
    "IntegrationEventStatus",
    "JobStatus",
    "Organization",
    "OrganizationMembership",
    "OrganizationRole",
    "OutboxEvent",
    "RevokedToken",
    "StepOperation",
    "SynchronizationAttempt",
    "SynchronizationJob",
    "User",
    "Workflow",
    "WorkflowExecution",
    "WorkflowStep",
]
