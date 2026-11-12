"""Data integrity: source-of-truth policies, detected conflicts and their resolutions.

SyncForge's employee record is fed by HR. The connected applications keep their own
copy of some of the same facts (name, e-mail, department, title, whether the account is
active), and those copies drift: someone edits a department in the Google Admin
console, a security team suspends a Slack account, a payroll clerk fixes a typo.

* A **policy** says, per field and organization, which side is authoritative -
  SyncForge (HR) or one specific connector - how serious a disagreement is, and whether
  SyncForge may fix it automatically. There is no built-in universal truth: without a
  row, the defaults in app/integrity/fields.py apply, and every one can be overridden.
* A **conflict** is one field on which one connector disagrees with SyncForge for one
  employee. Reconciliation never overwrites anything silently: it records the conflict;
  it is fixed only by a person, or automatically where the policy says so.
* A **resolution** is the decision taken (and by whom), kept as history.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PolicySource(enum.StrEnum):
    SYNCFORGE = "syncforge"  # the employee record in SyncForge (fed by HR) is right
    CONNECTOR = "connector"  # this connector's application is right


class ResolutionMode(enum.StrEnum):
    MANUAL = "manual"  # record the conflict; a person decides
    AUTO = "auto"  # apply the authoritative side's value as soon as it is detected


class ConflictSeverity(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConflictStatus(enum.StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ResolutionKind(enum.StrEnum):
    USE_SYNCFORGE = "use_syncforge"  # push SyncForge's value to the application
    USE_EXTERNAL = "use_external"  # adopt the application's value in SyncForge
    DISMISS = "dismiss"  # accepted difference / false positive: change nothing
    NO_LONGER_DIFFERENT = "no_longer_different"  # a later check found the values equal


CONFLICT_FIELDS = (
    "first_name",
    "last_name",
    "email",
    "department",
    "designation",
    "location",
    "account_active",
)


def _enum(cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [m.value for m in members],
    )


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{v}'" for v in values)})"


class DataSourcePolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_source_policies"
    __table_args__ = (
        UniqueConstraint("organization_id", "field"),
        CheckConstraint(_in("field", CONFLICT_FIELDS), name="field"),
        CheckConstraint(
            "(source = 'connector') = (connector_id IS NOT NULL)", name="connector_iff_source"
        ),
        ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_data_source_policies_connector_same_organization",
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[PolicySource] = mapped_column(_enum(PolicySource, "policy_source"))
    connector_id: Mapped[uuid.UUID | None] = mapped_column()
    resolution_mode: Mapped[ResolutionMode] = mapped_column(
        _enum(ResolutionMode, "resolution_mode")
    )
    severity: Mapped[ConflictSeverity] = mapped_column(_enum(ConflictSeverity, "conflict_severity"))


class DataConflict(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_conflicts"
    __table_args__ = (
        CheckConstraint(_in("field", CONFLICT_FIELDS), name="field"),
        CheckConstraint("times_detected >= 1", name="times_detected_positive"),
        ForeignKeyConstraint(
            ["organization_id", "employee_id"],
            ["employees.organization_id", "employees.id"],
            name="fk_data_conflicts_employee_same_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "connector_id"],
            ["connectors.organization_id", "connectors.id"],
            name="fk_data_conflicts_connector_same_organization",
            ondelete="CASCADE",
        ),
        # One open conflict per (employee, application, field): a repeated detection
        # updates it (times_detected) instead of piling up duplicates.
        Index(
            "uq_data_conflicts_open_employee_connector_field",
            "employee_id",
            "connector_id",
            "field",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_data_conflicts_organization_id_status", "organization_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    connector_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    field: Mapped[str] = mapped_column(String(30), nullable=False)
    # Both sides' values as text at the last detection. Names and e-mails are personal
    # data: shown to authorized members through the API, never logged or audited.
    syncforge_value: Mapped[str | None] = mapped_column(String(320))
    external_value: Mapped[str | None] = mapped_column(String(320))
    # The policy at detection time (copied: a later policy change does not rewrite it).
    authoritative_source: Mapped[PolicySource] = mapped_column(_enum(PolicySource, "policy_source"))
    severity: Mapped[ConflictSeverity] = mapped_column(_enum(ConflictSeverity, "conflict_severity"))
    status: Mapped[ConflictStatus] = mapped_column(
        _enum(ConflictStatus, "conflict_status"),
        nullable=False,
        server_default=ConflictStatus.OPEN.value,
    )
    # The employee's version at the last detection: adopting the external value is
    # refused if the employee changed since (someone decided on outdated information).
    employee_version: Mapped[int] = mapped_column(Integer, nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    times_detected: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # no values: they may be personal data
        return f"<DataConflict {self.id} {self.field} {self.status}>"


class ConflictResolution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conflict_resolutions"
    __table_args__ = (Index("ix_conflict_resolutions_conflict_id", "conflict_id"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    conflict_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("data_conflicts.id", ondelete="CASCADE"), nullable=False
    )
    resolution: Mapped[ResolutionKind] = mapped_column(_enum(ResolutionKind, "resolution_kind"))
    applied_value: Mapped[str | None] = mapped_column(String(320))
    # True when a person chose the non-authoritative side (allowed only with override and
    # a note).
    against_policy: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    automatic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    note: Mapped[str | None] = mapped_column(String(500))
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
