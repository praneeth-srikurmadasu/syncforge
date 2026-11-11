"""Concurrency test: the "last Organization Admin" rule holds under simultaneous requests.

Scenario: an organization has exactly two admins, A and B. A demotes B while, at the
same moment, B demotes A. Without row locking both requests could see "two admins",
both succeed, and the organization would be left with no admin at all.

This test uses two real, separately committed database sessions (not the rolled-back
test session), so it exercises PostgreSQL's actual SELECT ... FOR UPDATE locking.
"""

import threading
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.core.errors import ConflictError
from app.models import Organization, OrganizationMembership, OrganizationRole, User
from app.repositories.organizations import OrganizationRepository
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
