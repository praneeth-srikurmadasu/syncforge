"""Test data builders. Each creates a row and flushes it so its ID is available."""

import uuid

from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMembership, OrganizationRole, User
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
