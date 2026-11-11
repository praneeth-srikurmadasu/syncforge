"""Concurrency tests: business rules hold under simultaneous requests.

1. The "last Organization Admin" rule. An organization has exactly two admins, A and
   B. A demotes B while, at the same moment, B demotes A. Without row locking both
   requests could see "two admins", both succeed, and the organization would be left
   with no admin at all.

2. Reporting lines cannot form a cycle when two manager changes race.

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
