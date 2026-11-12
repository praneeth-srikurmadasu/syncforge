"""Workflows (what to do when an event happens) and their executions.

A *workflow* is configured by an administrator: a trigger (an employee event type) and
an ordered list of *steps*, each one connector operation (create the Slack user, suspend
the Google account, ...). Workflows are data, not code, so new automations need no
deployment.

When an event matches an active workflow, a worker creates a *workflow execution* and
one *synchronization job* per step. The jobs copy the step's connector and operation, so
editing a workflow later never rewrites history. Steps run in order; a failed step stops
the execution (later steps are marked skipped).

Every table here references its parents through composite (organization_id, id) foreign
keys, so a workflow can never use another organization's connector, and an execution can
never belong to another organization's event (ADR-0006).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Event types a workflow can be triggered by (same values as EmployeeEventType).
TRIGGER_EVENT_TYPES = (
    "employee.created",
    "employee.updated",
    "employee.department_changed",
    "employee.manager_changed",
    "employee.terminated",
)


class StepOperation(enum.StrEnum):
    CREATE_USER = "create_user"
    UPDATE_USER = "update_user"
    DEACTIVATE_USER = "deactivate_user"


class ExecutionStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStatus(enum.StrEnum):
    PENDING = "pending"  # not started yet
    RUNNING = "running"  # external call in progress
    RETRYING = "retrying"  # an attempt failed retryably; next one at next_attempt_at
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"  # an earlier step failed, so this one was not attempted


def _status_enum(cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [m.value for m in members],
    )


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


class Workflow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "id"),  # target of composite foreign keys
        CheckConstraint(_in_list("trigger_event_type", TRIGGER_EVENT_TYPES), name="trigger"),
        CheckConstraint("version >= 1", name="version_positive"),
        # Workers look up "active workflows of this organization for this event type".
        Index(
            "ix_workflows_organization_id_trigger_event_type",
            "organization_id",
            "trigger_event_type",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    trigger_event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # New workflows start inactive, so a half-configured workflow never runs.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    # Incremented whenever the trigger or steps change; executions record it.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.position",
        foreign_keys="[WorkflowStep.organization_id, WorkflowStep.workflow_id]",
    )

    def __repr__(self) -> str:
        return f"<Workflow {self.id} {self.trigger_event_type}>"


class WorkflowStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "position"),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint(_in_list("operation", tuple(StepOperation)), name="operation"),
        ForeignKeyConstraint(
            ["organization_id", "workflow_id"],
            ["workflows.organization_id", "workflows.id"],
            name="fk_workflow_steps_workflow_same_organization",
            ondelete="CASCADE",
        ),
        # No ON DELETE action: a connector used by a workflow cannot be deleted from
        # under it. Checked at commit (DEFERRABLE INITIALLY DEFERRED) so deleting a whole
        # organization - which cascades to both connectors and workflow steps in one
        # statement - is not refused because of the order the cascades run in.
        ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_workflow_steps_connector_same_organization",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_workflow_steps_connector_id", "connector_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3, ...
    connector_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)

    workflow: Mapped[Workflow] = relationship(
        back_populates="steps", foreign_keys=[organization_id, workflow_id]
    )

    def __repr__(self) -> str:
        return f"<WorkflowStep {self.position} {self.operation}>"


class WorkflowExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        # One execution per (event, workflow): a redelivered event resumes the existing
        # execution instead of starting a second one.
        UniqueConstraint("event_id", "workflow_id"),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["event_id"],
            ["integration_events.id"],
            name="fk_workflow_executions_event_id_integration_events",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "workflow_id"],
            ["workflows.organization_id", "workflows.id"],
            name="fk_workflow_executions_workflow_same_organization",
            ondelete="CASCADE",
        ),
        Index(
            "ix_workflow_executions_organization_id_workflow_id_created_at",
            "organization_id",
            "workflow_id",
            "created_at",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workflow_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(
        _status_enum(ExecutionStatus, "workflow_execution_status"),
        nullable=False,
        server_default=ExecutionStatus.RUNNING.value,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    jobs: Mapped[list["SynchronizationJob"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="SynchronizationJob.position",
        foreign_keys="[SynchronizationJob.organization_id, SynchronizationJob.execution_id]",
    )

    def __repr__(self) -> str:
        return f"<WorkflowExecution {self.id} {self.status}>"


class SynchronizationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "synchronization_jobs"
    __table_args__ = (
        UniqueConstraint("execution_id", "position"),
        UniqueConstraint("organization_id", "id"),  # target of the attempts' composite FK
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint(_in_list("operation", tuple(StepOperation)), name="operation"),
        ForeignKeyConstraint(
            ["organization_id", "execution_id"],
            ["workflow_executions.organization_id", "workflow_executions.id"],
            name="fk_synchronization_jobs_execution_same_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_synchronization_jobs_connector_same_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "employee_id"],
            ["employees.organization_id", "employees.id"],
            name="fk_synchronization_jobs_employee_same_organization",
            ondelete="CASCADE",
        ),
        Index("ix_synchronization_jobs_organization_id_status", "organization_id", "status"),
        Index("ix_synchronization_jobs_connector_id", "connector_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Copied from the workflow step when the execution starts.
    connector_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        _status_enum(JobStatus, "synchronization_job_status"),
        nullable=False,
        server_default=JobStatus.PENDING.value,
    )
    # Number of times the external call was attempted (history: synchronization_attempts).
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(String(255))
    error_category: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    execution: Mapped[WorkflowExecution] = relationship(
        back_populates="jobs", foreign_keys=[organization_id, execution_id]
    )
    attempt_history: Mapped[list["SynchronizationAttempt"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="SynchronizationAttempt.attempt_number",
        foreign_keys="[SynchronizationAttempt.organization_id, SynchronizationAttempt.job_id]",
    )

    def __repr__(self) -> str:
        return f"<SynchronizationJob {self.position} {self.operation} {self.status}>"


class AttemptOutcome(enum.StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    # The worker stopped (crash, kill) during the call; found and closed on resume.
    INTERRUPTED = "interrupted"


class SynchronizationAttempt(UUIDPrimaryKeyMixin, Base):
    """One external call made for a job: the retry history.

    Written when the call starts (outcome NULL) and completed when it ends, so a worker
    that dies mid-call leaves a visible, open attempt behind.
    """

    __tablename__ = "synchronization_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number"),
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
        ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["synchronization_jobs.organization_id", "synchronization_jobs.id"],
            name="fk_synchronization_attempts_job_same_organization",
            ondelete="CASCADE",
        ),
        Index(
            "ix_synchronization_attempts_organization_id_started_at",
            "organization_id",
            "started_at",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[AttemptOutcome | None] = mapped_column(
        _status_enum(AttemptOutcome, "synchronization_attempt_outcome")
    )
    error_category: Mapped[str | None] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))
    http_status: Mapped[int | None] = mapped_column(Integer)
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    retry_after_seconds: Mapped[float | None] = mapped_column(Float)
    # Set when this failure scheduled another attempt.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[SynchronizationJob] = relationship(
        back_populates="attempt_history", foreign_keys=[organization_id, job_id]
    )

    def __repr__(self) -> str:
        return f"<SynchronizationAttempt {self.attempt_number} {self.outcome}>"
