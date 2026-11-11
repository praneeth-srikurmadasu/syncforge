"""Tests for the demo data seed (python -m app.cli seed-demo)."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Employee, EmploymentStatus, OrganizationMembership, OrganizationRole
from app.seed import DEMO_SLUG, PEOPLE, SeedError, seed_demo
from tests.factories import create_organization, create_user


def employees_by_number(session: Session, organization_id: object) -> dict[str, Employee]:
    rows = session.scalars(select(Employee).where(Employee.organization_id == organization_id))
    return {e.employee_number: e for e in rows}


def test_seed_creates_demo_organization(db_session: Session) -> None:
    admin = create_user(db_session, email="demo-admin@example.com")

    result = seed_demo(db_session, admin_email="Demo-Admin@Example.com")

    assert (result.departments, result.employees) == (5, 20)
    assert result.organization.slug == DEMO_SLUG
    membership = db_session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == result.organization.id
        )
    )
    assert membership is not None
    assert (membership.user_id, membership.role) == (admin.id, OrganizationRole.ORG_ADMIN)


def test_seed_has_lifecycle_variety_and_a_valid_hierarchy(db_session: Session) -> None:
    create_user(db_session, email="demo-admin@example.com")
    result = seed_demo(db_session, admin_email="demo-admin@example.com")
    people = employees_by_number(db_session, result.organization.id)

    assert len(people) == len(PEOPLE)
    statuses = sorted(e.employment_status.value for e in people.values())
    assert statuses.count("on_leave") == 1
    assert statuses.count("terminated") == 1
    # The terminated Account Executive's report moved up to the Head of Sales.
    assert people["AC-014"].employment_status is EmploymentStatus.TERMINATED
    assert people["AC-016"].manager_id == people["AC-004"].id
    # Exactly one person (the CEO) has no manager, and nobody reports to a terminated one.
    assert [e.employee_number for e in people.values() if e.manager_id is None] == ["AC-001"]
    terminated_ids = {e.id for e in people.values() if e.termination_date is not None}
    assert not any(e.manager_id in terminated_ids for e in people.values())


def test_seed_refuses_to_run_twice(db_session: Session) -> None:
    create_user(db_session, email="demo-admin@example.com")
    seed_demo(db_session, admin_email="demo-admin@example.com")

    with pytest.raises(SeedError, match="already exists"):
        seed_demo(db_session, admin_email="demo-admin@example.com")


def test_seed_requires_a_registered_user(db_session: Session) -> None:
    with pytest.raises(SeedError, match="Register first"):
        seed_demo(db_session, admin_email="nobody@example.com")


def test_seed_refuses_if_slug_is_taken(db_session: Session) -> None:
    create_user(db_session, email="demo-admin@example.com")
    create_organization(db_session, slug=DEMO_SLUG)

    with pytest.raises(SeedError, match="already exists"):
        seed_demo(db_session, admin_email="demo-admin@example.com")
