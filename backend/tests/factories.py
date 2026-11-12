"""Test data builders. Each creates a row and flushes it so its ID is available."""

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models import (
    Connector,
    Department,
    Employee,
    EmploymentStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    User,
)
from app.security.passwords import hash_password
from app.security.tokens import create_access_token

DEFAULT_PASSWORD = "correct-horse-battery"


def create_user(
    session: Session,
    *,
    email: str | None = None,
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Test User",
    is_active: bool = True,
    is_superadmin: bool = False,
) -> User:
    user = User(
        email=email or f"user-{uuid.uuid4().hex[:10]}@example.com",
        full_name=full_name,
        password_hash=hash_password(password),
        is_active=is_active,
        is_superadmin=is_superadmin,
    )
    session.add(user)
    session.flush()
    return user


def create_organization(
    session: Session, *, name: str = "Acme Corp", slug: str | None = None
) -> Organization:
    org = Organization(name=name, slug=slug or f"org-{uuid.uuid4().hex[:10]}")
    session.add(org)
    session.flush()
    return org


def add_member(
    session: Session, user: User, organization: Organization, role: OrganizationRole
) -> OrganizationMembership:
    membership = OrganizationMembership(user=user, organization=organization, role=role)
    session.add(membership)
    session.flush()
    return membership


def auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id).token}"}


def create_department(session: Session, organization: Organization, name: str) -> Department:
    department = Department(organization_id=organization.id, name=name)
    session.add(department)
    session.flush()
    return department


def create_employee(
    session: Session,
    organization: Organization,
    *,
    first_name: str = "Grace",
    last_name: str = "Hopper",
    email: str | None = None,
    employee_number: str | None = None,
    department: Department | None = None,
    manager: Employee | None = None,
    designation: str | None = "Engineer",
    location: str | None = "Bengaluru",
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE,
    joining_date: date = date(2024, 1, 15),
    termination_date: date | None = None,
) -> Employee:
    suffix = uuid.uuid4().hex[:8]
    employee = Employee(
        organization_id=organization.id,
        employee_number=employee_number or f"E-{suffix}",
        first_name=first_name,
        last_name=last_name,
        email=email or f"{first_name.lower()}.{suffix}@acme.example",
        department_id=department.id if department else None,
        manager_id=manager.id if manager else None,
        designation=designation,
        location=location,
        employment_status=employment_status,
        joining_date=joining_date,
        termination_date=termination_date,
    )
    session.add(employee)
    session.flush()
    return employee


def create_connector(
    session: Session,
    organization: Organization,
    *,
    connector_type: str = "slack",
    name: str | None = None,
) -> Connector:
    """A connector row without credentials (for database-level tests)."""
    connector = Connector(
        organization_id=organization.id,
        connector_type=connector_type,
        connector_version="1.0.0",
        name=name or f"{connector_type}-{uuid.uuid4().hex[:6]}",
    )
    session.add(connector)
    session.flush()
    return connector
