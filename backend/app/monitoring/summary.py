"""One organization's figures in one query round: what the dashboard shows.

Counts use the same conditions as the list endpoints (archived employees excluded,
open dead letters and conflicts), so a figure here equals the `total` of the matching
list request. Processing durations come from event timestamps:

* end to end - from the employee change (event recorded) to completion;
* final attempt - from the last time a worker picked the event up to completion: the
  worker time of the attempt that succeeded (`started_at` is set on every pickup, so
  retry waits are not included). The difference to end to end is queueing, retries and
  waits for rate limits or open circuits.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Float, cast, extract, func, select
from sqlalchemy.orm import Session

from app.models import (
    ConflictSeverity,
    ConflictStatus,
    Connector,
    ConnectorStatus,
    DataConflict,
    DeadLetterEvent,
    DeadLetterStatus,
    Employee,
    EmploymentStatus,
    IntegrationEvent,
    IntegrationEventStatus,
    Workflow,
)

DURATION_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class Durations:
    p50: float
    p95: float
    max: float


@dataclass(frozen=True)
class ProcessingStats:
    window_hours: int
    completed: int
    end_to_end_seconds: Durations | None
    processing_seconds: Durations | None


@dataclass(frozen=True)
class OrganizationSummary:
    generated_at: datetime
    employees: dict[str, int]
    workflows: dict[str, int]
    connectors: dict[str, int]
    events: dict[str, int]
    dead_letters_open: int
    conflicts_open: dict[str, int]
    processing: ProcessingStats


def _counts(session: Session, column, *conditions) -> dict[str, int]:  # noqa: ANN001
    return {
        (key.value if hasattr(key, "value") else str(key)): count
        for key, count in session.execute(
            select(column, func.count()).where(*conditions).group_by(column)
        )
    }


def _durations(session: Session, seconds, *conditions) -> Durations | None:  # noqa: ANN001
    p50, p95, longest = session.execute(
        select(
            func.percentile_cont(0.5).within_group(seconds),
            func.percentile_cont(0.95).within_group(seconds),
            func.max(seconds),
        ).where(*conditions)
    ).one()
    if p50 is None:
        return None
    return Durations(p50=round(p50, 3), p95=round(p95, 3), max=round(longest, 3))


def organization_summary(
    session: Session, organization_id: uuid.UUID, now: datetime | None = None
) -> OrganizationSummary:
    now = now or datetime.now(UTC)
    org = organization_id

    employees = {s.value: 0 for s in EmploymentStatus}
    employees.update(
        _counts(
            session,
            Employee.employment_status,
            Employee.organization_id == org,
            Employee.archived_at.is_(None),
        )
    )
    active_workflows = _counts(session, Workflow.is_active, Workflow.organization_id == org)
    connectors = {s.value: 0 for s in ConnectorStatus}
    connectors.update(_counts(session, Connector.status, Connector.organization_id == org))
    events = {s.value: 0 for s in IntegrationEventStatus}
    events.update(
        _counts(session, IntegrationEvent.status, IntegrationEvent.organization_id == org)
    )
    conflicts = {s.value: 0 for s in ConflictSeverity}
    conflicts.update(
        _counts(
            session,
            DataConflict.severity,
            DataConflict.organization_id == org,
            DataConflict.status == ConflictStatus.OPEN,
        )
    )
    dead_letters = session.scalar(
        select(func.count()).where(
            DeadLetterEvent.organization_id == org, DeadLetterEvent.status == DeadLetterStatus.OPEN
        )
    )

    recent = (
        IntegrationEvent.organization_id == org,
        IntegrationEvent.status == IntegrationEventStatus.COMPLETED,
        IntegrationEvent.completed_at >= now - DURATION_WINDOW,
    )
    end_to_end = cast(
        extract("epoch", IntegrationEvent.completed_at - IntegrationEvent.created_at), Float
    )
    processing = cast(
        extract("epoch", IntegrationEvent.completed_at - IntegrationEvent.started_at), Float
    )
    completed = session.scalar(select(func.count()).where(*recent)) or 0

    return OrganizationSummary(
        generated_at=now,
        employees=employees,
        workflows={
            "active": active_workflows.get("True", 0),
            "total": sum(active_workflows.values()),
        },
        connectors={**connectors, "total": sum(connectors.values())},
        events=events,
        dead_letters_open=dead_letters or 0,
        conflicts_open={**conflicts, "total": sum(conflicts.values())},
        processing=ProcessingStats(
            window_hours=int(DURATION_WINDOW.total_seconds() // 3600),
            completed=completed,
            end_to_end_seconds=_durations(session, end_to_end, *recent),
            processing_seconds=_durations(
                session, processing, *recent, IntegrationEvent.started_at.is_not(None)
            ),
        ),
    )
