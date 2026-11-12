"""Concurrency tests: business rules hold under simultaneous requests.

1. The "last Organization Admin" rule. An organization has exactly two admins, A and
   B. A demotes B while, at the same moment, B demotes A. Without row locking both
   requests could see "two admins", both succeed, and the organization would be left
   with no admin at all.

2. Reporting lines cannot form a cycle when two manager changes race.

3. A worker receiving a retry message while the outbox relay still holds the event row
   (it publishes first, then commits) claims the event instead of skipping it.

4. Two users replay the same dead-letter entry at the same moment: exactly one replay
   happens; the other waits for the row lock, re-reads, and gets `already_replayed`.

These tests use two real, separately committed database sessions (not the rolled-back
test session), so they exercise PostgreSQL's actual locking.
"""

import threading
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.core.errors import ConflictError, UnprocessableError
from app.models import Employee, Organization, OrganizationMembership, OrganizationRole, User
from app.repositories.employees import EmployeeRepository
from app.repositories.organizations import OrganizationRepository
from app.services.employees import EmployeeService
from app.services.organizations import OrganizationService


@pytest.fixture
def org_with_two_admins() -> Iterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    suffix = uuid.uuid4().hex[:8]
    with SessionLocal() as session:
        org = Organization(name="Race Corp", slug=f"race-{suffix}")
        admin_a = User(email=f"a-{suffix}@example.com", full_name="A", password_hash="x")
        admin_b = User(email=f"b-{suffix}@example.com", full_name="B", password_hash="x")
        session.add_all([org, admin_a, admin_b])
        session.flush()
        for admin in (admin_a, admin_b):
            session.add(
                OrganizationMembership(
                    organization=org, user=admin, role=OrganizationRole.ORG_ADMIN
                )
            )
        session.commit()
        ids = (org.id, admin_a.id, admin_b.id)
    yield ids
    with SessionLocal() as session:  # committed data: clean up explicitly
        session.execute(delete(Organization).where(Organization.id == ids[0]))
        session.execute(delete(User).where(User.id.in_(ids[1:])))
        session.commit()


def test_simultaneous_demotions_cannot_remove_every_admin(
    org_with_two_admins: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    org_id, admin_a, admin_b = org_with_two_admins
    outcome: dict[str, object] = {}

    # Session 1 (request by B) takes the admin-row locks and holds them.
    first = SessionLocal()
    OrganizationRepository(first).lock_admin_memberships(org_id)

    # Session 2 (request by A, demoting B) runs in another thread and must block.
    def demote_b() -> None:
        with SessionLocal() as second:
            organization = second.get(Organization, org_id)
            try:
                OrganizationService(second).change_role(
                    organization, user_id=admin_b, role=OrganizationRole.VIEWER
                )
                outcome["second"] = "succeeded"
            except ConflictError as exc:
                outcome["second"] = exc.code

    worker = threading.Thread(target=demote_b)
    worker.start()
    worker.join(timeout=1.0)
    assert worker.is_alive(), "second request should be waiting on the row lock"

    # Session 1 finishes its own change (demote A) and commits, releasing the locks.
    organization = first.get(Organization, org_id)
    OrganizationService(first).change_role(
        organization, user_id=admin_a, role=OrganizationRole.VIEWER
    )
    first.close()

    worker.join(timeout=10)
    assert not worker.is_alive()
    # Session 2 re-checked after the lock was released and saw B is the last admin.
    assert outcome["second"] == "last_admin"

    with SessionLocal() as check:
        admins = check.scalar(
            select(func.count())
            .select_from(OrganizationMembership)
            .where(
                OrganizationMembership.organization_id == org_id,
                OrganizationMembership.role == OrganizationRole.ORG_ADMIN,
            )
        )
    assert admins == 1


# ---- reporting lines -----------------------------------------------------------------


@pytest.fixture
def org_with_two_employees() -> Iterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    suffix = uuid.uuid4().hex[:8]
    with SessionLocal() as session:
        org = Organization(name="Cycle Corp", slug=f"cycle-{suffix}")
        session.add(org)
        session.flush()
        people = [
            Employee(
                organization_id=org.id,
                employee_number=f"E-{name}",
                first_name=name,
                last_name="Race",
                email=f"{name.lower()}-{suffix}@example.com",
                joining_date=date(2024, 1, 1),
            )
            for name in ("Alice", "Bob")
        ]
        session.add_all(people)
        session.commit()
        ids = (org.id, people[0].id, people[1].id)
    yield ids
    with SessionLocal() as session:
        session.execute(delete(Organization).where(Organization.id == ids[0]))
        session.commit()


def test_simultaneous_manager_changes_cannot_form_a_cycle(
    org_with_two_employees: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    """Request 1 sets "Bob reports to Alice" while request 2 sets "Alice reports to Bob".

    Each request locks a *different* employee row, so row locks alone would let both
    succeed and create a cycle. The per-organization advisory lock serializes them.
    """
    org_id, alice, bob = org_with_two_employees
    outcome: dict[str, object] = {}

    first = SessionLocal()
    EmployeeRepository(first).lock_hierarchy(org_id)

    def alice_reports_to_bob() -> None:
        with SessionLocal() as second:
            organization = second.get(Organization, org_id)
            try:
                EmployeeService(second).update(organization, alice, {"manager_id": bob})
                outcome["second"] = "succeeded"
            except UnprocessableError as exc:
                outcome["second"] = exc.code

    worker = threading.Thread(target=alice_reports_to_bob)
    worker.start()
    worker.join(timeout=1.0)
    assert worker.is_alive(), "second request should be waiting on the hierarchy lock"

    organization = first.get(Organization, org_id)
    EmployeeService(first).update(organization, bob, {"manager_id": alice})  # commits
    first.close()

    worker.join(timeout=10)
    assert not worker.is_alive()
    assert outcome["second"] == "manager_cycle"

    with SessionLocal() as check:
        managers = dict(
            check.execute(
                select(Employee.id, Employee.manager_id).where(Employee.organization_id == org_id)
            ).all()
        )
    assert managers == {alice: None, bob: alice}


@pytest.fixture
def due_retry_event() -> Iterator[uuid.UUID]:
    from datetime import UTC, datetime, timedelta

    from app.models import IntegrationEvent, IntegrationEventStatus

    suffix = uuid.uuid4().hex[:8]
    with SessionLocal() as session:
        org = Organization(name="Retry Race", slug=f"retry-race-{suffix}")
        session.add(org)
        session.flush()
        employee = Employee(
            organization_id=org.id,
            employee_number="E-1",
            first_name="R",
            last_name="R",
            email=f"r-{suffix}@example.com",
            joining_date=date(2026, 11, 1),
        )
        session.add(employee)
        session.flush()
        event = IntegrationEvent(
            organization_id=org.id,
            event_type="employee.created",
            employee_id=employee.id,
            payload={},
            status=IntegrationEventStatus.RETRYING,
            next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        session.add(event)
        session.commit()
        org_id, event_id = org.id, event.id
    yield event_id
    with SessionLocal() as session:
        session.execute(delete(Organization).where(Organization.id == org_id))
        session.commit()


def test_a_worker_claims_a_due_retry_even_while_the_relay_holds_the_row(
    due_retry_event: uuid.UUID,
) -> None:
    """Found in the live retry demonstration: the worker skipped the third attempt."""
    from app.models import IntegrationEvent, IntegrationEventStatus
    from app.workflows.engine import EventProcessor

    relay_session = SessionLocal()
    row = relay_session.scalars(
        select(IntegrationEvent)
        .where(IntegrationEvent.id == due_retry_event)
        .with_for_update(skip_locked=True)
    ).one()  # the relay holds the row and has just published the message
    outcome: dict[str, object] = {}

    def worker() -> None:
        with SessionLocal() as session:
            outcome["claimed"] = EventProcessor(session)._claim(due_retry_event) is not None

    thread = threading.Thread(target=worker)
    try:
        thread.start()
        thread.join(timeout=0.5)
        waited = thread.is_alive()
        row.status = IntegrationEventStatus.PENDING  # the relay commits after publishing
        relay_session.commit()
    finally:
        relay_session.close()  # never leave the row locked, even if an assertion fails
        thread.join(timeout=10)

    assert waited, "the worker must wait for the relay's transaction"
    assert outcome == {"claimed": True}


# ---- dead-letter replay ----------------------------------------------------------------


@pytest.fixture
def dead_lettered() -> Iterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    """A committed organization with one dead-lettered event: (org, entry, user)."""
    from datetime import UTC, datetime

    from app.models import (
        Connector,
        DeadLetterEvent,
        DeadLetterReason,
        ExecutionStatus,
        IntegrationEvent,
        IntegrationEventStatus,
        JobStatus,
        SynchronizationJob,
        Workflow,
        WorkflowExecution,
        WorkflowStep,
    )

    suffix = uuid.uuid4().hex[:8]
    with SessionLocal() as session:
        org = Organization(name="Replay Race", slug=f"replay-race-{suffix}")
        user = User(email=f"replay-{suffix}@example.com", full_name="R", password_hash="x")
        session.add_all([org, user])
        session.flush()
        connector = Connector(
            organization_id=org.id, connector_type="slack", connector_version="1.0.0", name="s"
        )
        employee = Employee(
            organization_id=org.id,
            employee_number="E-1",
            first_name="R",
            last_name="R",
            email=f"r-{suffix}@example.com",
            joining_date=date(2026, 11, 1),
        )
        session.add_all([connector, employee])
        session.flush()
        workflow = Workflow(
            organization_id=org.id,
            name="Onboarding",
            trigger_event_type="employee.created",
            is_active=True,
        )
        workflow.steps = [
            WorkflowStep(
                organization_id=org.id,
                position=1,
                connector_id=connector.id,
                operation="create_user",
            )
        ]
        event = IntegrationEvent(
            organization_id=org.id,
            event_type="employee.created",
            employee_id=employee.id,
            payload={},
            status=IntegrationEventStatus.DEAD_LETTER,
        )
        session.add_all([workflow, event])
        session.flush()
        execution = WorkflowExecution(
            organization_id=org.id,
            event_id=event.id,
            workflow_id=workflow.id,
            workflow_version=1,
            status=ExecutionStatus.FAILED,
        )
        execution.jobs = [
            SynchronizationJob(
                organization_id=org.id,
                position=1,
                connector_id=connector.id,
                operation="create_user",
                employee_id=employee.id,
                status=JobStatus.FAILED,
                attempts=1,
            )
        ]
        session.add(execution)
        session.flush()
        entry = DeadLetterEvent(
            organization_id=org.id,
            event_id=event.id,
            reason=DeadLetterReason.NON_RETRYABLE,
            job_id=execution.jobs[0].id,
            attempts=1,
            dead_lettered_at=datetime.now(UTC),
        )
        session.add(entry)
        session.commit()
        ids = (org.id, entry.id, user.id)
    yield ids
    with SessionLocal() as session:
        session.execute(delete(Organization).where(Organization.id == ids[0]))
        session.execute(delete(User).where(User.id == ids[2]))
        session.commit()


def test_simultaneous_replays_of_one_entry_replay_it_once(
    dead_lettered: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    from app.models import OutboxEvent
    from app.repositories.dead_letters import DeadLetterRepository
    from app.services.dead_letters import DeadLetterService

    org_id, entry_id, user_id = dead_lettered
    outcome: dict[str, object] = {}

    # Request 1 has locked the entry (the first step of a replay) and holds the lock.
    first = SessionLocal()
    DeadLetterRepository(first).get(org_id, entry_id, for_update=True)

    def second_replay() -> None:
        with SessionLocal() as second:
            try:
                DeadLetterService(second).replay(
                    second.get(Organization, org_id), entry_id, second.get(User, user_id)
                )
                outcome["second"] = "replayed"
            except ConflictError as exc:
                outcome["second"] = exc.code

    thread = threading.Thread(target=second_replay)
    try:
        thread.start()
        thread.join(timeout=1.0)
        waited = thread.is_alive()
        DeadLetterService(first).replay(
            first.get(Organization, org_id), entry_id, first.get(User, user_id)
        )
    finally:
        first.close()
        thread.join(timeout=10)

    assert waited, "the second replay must wait for the first one's lock"
    assert outcome == {"second": "already_replayed"}
    with SessionLocal() as check:
        entry = DeadLetterRepository(check).get(org_id, entry_id)
        outbox_rows = check.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_id == entry.event_id)
        )
    assert outbox_rows == 1  # one replay was queued, not two
