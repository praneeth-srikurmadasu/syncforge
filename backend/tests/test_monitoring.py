"""Observability: organization summary, processing durations, heartbeats, system status."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    ComponentHeartbeat,
    ConflictSeverity,
    ConnectorStatus,
    DataConflict,
    DeadLetterEvent,
    DeadLetterReason,
    Employee,
    EmploymentStatus,
    IntegrationEvent,
    IntegrationEventStatus,
    Organization,
    OrganizationRole,
    OutboxEvent,
    PolicySource,
    Workflow,
)
from app.monitoring.heartbeat import Heartbeat, beat
from app.monitoring.status import system_status
from app.monitoring.summary import organization_summary
from tests.factories import (
    add_member,
    auth_headers,
    create_connector,
    create_employee,
    create_organization,
    create_user,
)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _event(
    session: Session,
    org: Organization,
    employee: Employee,
    status: IntegrationEventStatus,
    *,
    created: datetime | None = None,
    started: datetime | None = None,
    completed: datetime | None = None,
    locked_until: datetime | None = None,
) -> IntegrationEvent:
    event = IntegrationEvent(
        organization_id=org.id,
        event_type="employee.created",
        employee_id=employee.id,
        payload={},
        status=status,
        started_at=started,
        completed_at=completed,
        locked_until=locked_until,
    )
    if created is not None:
        event.created_at = created
    session.add(event)
    session.flush()
    return event


@pytest.fixture
def populated(db_session: Session) -> Organization:
    """An organization with something in every category, plus a second organization
    whose data must never be counted."""
    org, other = create_organization(db_session), create_organization(db_session)
    people = [
        create_employee(db_session, org),
        create_employee(db_session, org),
        create_employee(db_session, org, employment_status=EmploymentStatus.ON_LEAVE),
    ]
    gone = create_employee(
        db_session,
        org,
        employment_status=EmploymentStatus.TERMINATED,
        termination_date=datetime(2025, 1, 1).date(),
    )
    archived = create_employee(
        db_session,
        org,
        employment_status=EmploymentStatus.TERMINATED,
        termination_date=datetime(2025, 1, 1).date(),
    )
    archived.archived_at = datetime.now(UTC)
    create_employee(db_session, other)

    slack = create_connector(db_session, org)
    payroll = create_connector(db_session, org, connector_type="payroll")
    payroll.status = ConnectorStatus.CONNECTED
    create_connector(db_session, other)

    db_session.add_all(
        [
            Workflow(
                organization_id=org.id,
                name="On",
                trigger_event_type="employee.created",
                is_active=True,
            ),
            Workflow(organization_id=org.id, name="Off", trigger_event_type="employee.terminated"),
        ]
    )
    for status in (
        IntegrationEventStatus.PENDING,
        IntegrationEventStatus.RETRYING,
        IntegrationEventStatus.COMPLETED,
        IntegrationEventStatus.COMPLETED,
        IntegrationEventStatus.DEAD_LETTER,
    ):
        _event(db_session, org, people[0], status)
    failed = _event(db_session, org, gone, IntegrationEventStatus.DEAD_LETTER)
    db_session.add(
        DeadLetterEvent(
            organization_id=org.id,
            event_id=failed.id,
            reason=DeadLetterReason.NON_RETRYABLE,
            attempts=1,
            dead_lettered_at=NOW,
        )
    )
    for severity, field in (
        (ConflictSeverity.HIGH, "department"),
        (ConflictSeverity.LOW, "location"),
    ):
        db_session.add(
            DataConflict(
                organization_id=org.id,
                employee_id=people[1].id,
                connector_id=slack.id,
                field=field,
                syncforge_value="a",
                external_value="b",
                authoritative_source=PolicySource.SYNCFORGE,
                severity=severity,
                employee_version=1,
                first_detected_at=NOW,
                last_detected_at=NOW,
            )
        )
    db_session.flush()
    return org


def test_summary_counts_equal_the_list_endpoints_totals(
    client: TestClient, db_session: Session, populated: Organization
) -> None:
    admin = create_user(db_session)
    add_member(db_session, admin, populated, OrganizationRole.ORG_ADMIN)
    headers = auth_headers(admin)
    base = f"/api/v1/organizations/{populated.id}"

    def total(path: str, **params: str) -> int:
        response = client.get(f"{base}/{path}", params={"limit": 1, **params}, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()["total"]

    summary = client.get(f"{base}/summary", headers=headers)
    assert summary.status_code == 200
    s = summary.json()

    for status in ("active", "on_leave", "terminated"):
        assert s["employees"][status] == total("employees", employment_status=status)
    assert s["employees"] == {"active": 2, "on_leave": 1, "terminated": 1}  # archived excluded
    assert s["workflows"] == {"active": 1, "total": 2}
    assert s["workflows"]["active"] == total("workflows", is_active="true")
    assert s["connectors"]["total"] == total("connectors") == 2
    assert s["connectors"]["connected"] == 1 and s["connectors"]["pending"] == 1
    for status, count in s["events"].items():
        assert count == total("events", event_status=status), status
    assert s["dead_letters_open"] == total("dead-letter-events", entry_status="open") == 1
    assert s["conflicts_open"]["total"] == total("conflicts", conflict_status="open") == 2
    assert s["conflicts_open"]["high"] == total(
        "conflicts", conflict_status="open", severity="high"
    )


def test_summary_needs_membership_but_any_role(
    client: TestClient, db_session: Session, populated: Organization
) -> None:
    viewer, outsider = create_user(db_session), create_user(db_session)
    add_member(db_session, viewer, populated, OrganizationRole.VIEWER)
    url = f"/api/v1/organizations/{populated.id}/summary"
    assert client.get(url, headers=auth_headers(viewer)).status_code == 200
    assert client.get(url, headers=auth_headers(outsider)).status_code == 404
    assert client.get(url).status_code == 401


def test_processing_durations_cover_the_last_day_only(db_session: Session) -> None:
    org = create_organization(db_session)
    person = create_employee(db_session, org)
    # Completed within 24 h: end to end 1, 2, 3, 4 and 10 s; final attempt 0.5 s each.
    for seconds in (1, 2, 3, 4, 10):
        created = NOW - timedelta(hours=1)
        completed = created + timedelta(seconds=seconds)
        _event(
            db_session,
            org,
            person,
            IntegrationEventStatus.COMPLETED,
            created=created,
            started=completed - timedelta(seconds=0.5),
            completed=completed,
        )
    # Too old, or not completed: ignored.
    old = NOW - timedelta(days=2)
    _event(
        db_session,
        org,
        person,
        IntegrationEventStatus.COMPLETED,
        created=old,
        started=old,
        completed=old + timedelta(seconds=99),
    )
    _event(db_session, org, person, IntegrationEventStatus.RETRYING, created=NOW)

    stats = organization_summary(db_session, org.id, now=NOW).processing
    assert stats.window_hours == 24
    assert stats.completed == 5
    assert stats.end_to_end_seconds is not None
    assert stats.end_to_end_seconds.p50 == pytest.approx(3.0)
    assert stats.end_to_end_seconds.p95 == pytest.approx(8.8)  # linear interpolation
    assert stats.end_to_end_seconds.max == pytest.approx(10.0)
    assert stats.processing_seconds is not None
    assert stats.processing_seconds.p50 == pytest.approx(0.5)


def test_no_completed_events_means_no_durations(db_session: Session) -> None:
    org = create_organization(db_session)
    stats = organization_summary(db_session, org.id, now=NOW).processing
    assert stats.completed == 0
    assert stats.end_to_end_seconds is None and stats.processing_seconds is None


# ---- heartbeats and system status ----------------------------------------------------------


def test_beat_inserts_then_updates_and_forgets_old_instances(db_session: Session) -> None:
    started = NOW - timedelta(minutes=5)
    beat(db_session, "relay", "old-host:1", started_at=started, now=NOW - timedelta(days=2))
    beat(db_session, "worker", "host:42", started_at=started, now=NOW - timedelta(seconds=30))
    beat(db_session, "worker", "host:42", started_at=started, now=NOW)

    rows = db_session.scalars(select(ComponentHeartbeat)).all()
    assert [(r.component, r.instance, r.last_seen_at) for r in rows] == [("worker", "host:42", NOW)]
    assert rows[0].started_at == started


def test_heartbeat_beats_at_most_once_per_interval(db_session: Session) -> None:
    calls: list[int] = []

    class CountingSession:
        def __enter__(self) -> Session:
            calls.append(1)
            return db_session

        def __exit__(self, *_: object) -> None:
            return None

    heartbeat = Heartbeat("relay", 15, CountingSession)
    for t in (100.0, 105.0, 114.9, 115.0, 129.0, 130.5):
        heartbeat.maybe_beat(t)
    assert len(calls) == 3  # at 100, 115 and 130.5


def test_system_status_reports_stale_components_and_stuck_events(db_session: Session) -> None:
    settings = get_settings()
    org = create_organization(db_session)
    person = create_employee(db_session, org)
    started = NOW - timedelta(hours=1)
    beat(db_session, "worker", "w:1", started_at=started, now=NOW - timedelta(seconds=10))
    beat(db_session, "relay", "r:1", started_at=started, now=NOW - timedelta(seconds=300))

    stuck = _event(
        db_session,
        org,
        person,
        IntegrationEventStatus.PROCESSING,
        locked_until=NOW - timedelta(minutes=1),
    )
    _event(
        db_session,
        org,
        person,
        IntegrationEventStatus.PROCESSING,
        locked_until=NOW + timedelta(minutes=1),
    )
    pending = _event(
        db_session, org, person, IntegrationEventStatus.PENDING, created=NOW - timedelta(seconds=40)
    )
    db_session.add(OutboxEvent(event_id=pending.id, created_at=NOW - timedelta(seconds=40)))
    db_session.flush()

    status = system_status(db_session, settings, now=NOW)
    assert status.healthy is False
    assert status.components["worker"][0].healthy is True
    assert status.components["relay"][0].healthy is False
    assert status.components["relay"][0].seconds_since_seen == 300
    assert any("relay" in p for p in status.problems)
    assert any("past their processing lease" in p for p in status.problems)
    assert status.events_stuck_processing == 1 and stuck.id
    assert status.outbox_unpublished >= 1
    assert status.outbox_oldest_unpublished_seconds is not None
    assert status.events_oldest_pending_seconds is not None


def test_system_status_is_for_super_admins_only(client: TestClient, db_session: Session) -> None:
    member = create_user(db_session)
    root = create_user(db_session, is_superadmin=True)
    refused = client.get("/api/v1/system/status", headers=auth_headers(member))
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "superadmin_required"

    body = client.get("/api/v1/system/status", headers=auth_headers(root)).json()
    assert set(body["components"]) >= {"worker", "relay"}
    assert set(body["events_by_status"]) == {s.value for s in IntegrationEventStatus}
    # No heartbeats in the test database, so nothing is reported as healthy.
    assert body["healthy"] is False


def test_ready_does_not_depend_on_background_processes(client: TestClient) -> None:
    # Workers down must never take the API out of service: events wait in the outbox.
    assert client.get("/ready").status_code == 200
