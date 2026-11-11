"""Database constraint tests: the schema itself rejects invalid data.

Constraints in the database are the last line of defence - they hold even if
application code has a bug or someone writes to the table directly.
"""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationMembership, OrganizationRole, User


def make_user(session: Session, email: str = "alice@example.com") -> User:
    user = User(email=email, full_name="Alice Example", password_hash="not-a-real-hash")
    session.add(user)
    session.flush()
    return user


def make_org(session: Session, slug: str = "acme") -> Organization:
    org = Organization(name="Acme Corp", slug=slug)
    session.add(org)
    session.flush()
    return org


def test_server_defaults_are_applied(db_session: Session) -> None:
    user = make_user(db_session)
    org = make_org(db_session)
    db_session.refresh(user)
    db_session.refresh(org)

    assert user.is_active is True
    assert user.is_superadmin is False
    assert user.created_at is not None
    assert user.updated_at is not None
    assert org.is_active is True


def test_membership_links_user_and_organization(db_session: Session) -> None:
    user = make_user(db_session)
    org = make_org(db_session)
    db_session.add(
        OrganizationMembership(user=user, organization=org, role=OrganizationRole.ORG_ADMIN)
    )
    db_session.flush()
    db_session.expire_all()

    membership = db_session.scalars(select(OrganizationMembership)).one()
    assert membership.role is OrganizationRole.ORG_ADMIN
    assert membership.user.id == user.id
    assert membership.organization.slug == "acme"


def test_duplicate_email_is_rejected(db_session: Session) -> None:
    make_user(db_session, "dup@example.com")

    with pytest.raises(IntegrityError, match="uq_users_email"):
        make_user(db_session, "dup@example.com")


def test_uppercase_email_is_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
        make_user(db_session, "Alice@Example.com")


def test_duplicate_organization_slug_is_rejected(db_session: Session) -> None:
    make_org(db_session, "acme")

    with pytest.raises(IntegrityError, match="uq_organizations_slug"):
        make_org(db_session, "acme")


@pytest.mark.parametrize("bad_slug", ["Acme", "acme corp", "-acme", "acme-", "acme--corp", ""])
def test_invalid_organization_slug_is_rejected(db_session: Session, bad_slug: str) -> None:
    with pytest.raises(IntegrityError, match="ck_organizations_slug_format"):
        make_org(db_session, bad_slug)


def test_user_cannot_have_two_memberships_in_one_organization(db_session: Session) -> None:
    user = make_user(db_session)
    org = make_org(db_session)
    db_session.add(
        OrganizationMembership(user=user, organization=org, role=OrganizationRole.VIEWER)
    )
    db_session.flush()

    db_session.add(
        OrganizationMembership(user=user, organization=org, role=OrganizationRole.ORG_ADMIN)
    )
    with pytest.raises(IntegrityError, match="uq_organization_memberships_organization_id_user_id"):
        db_session.flush()


def test_unknown_role_is_rejected_by_database(db_session: Session) -> None:
    user = make_user(db_session)
    org = make_org(db_session)

    # Raw SQL bypasses the Python enum, proving the database enforces the role list.
    with pytest.raises(IntegrityError, match="ck_organization_memberships_organization_role"):
        db_session.execute(
            text(
                "INSERT INTO organization_memberships (id, organization_id, user_id, role) "
                "VALUES (gen_random_uuid(), :org, :user, 'owner')"
            ),
            {"org": org.id, "user": user.id},
        )


def test_deleting_organization_deletes_its_memberships(db_session: Session) -> None:
    user = make_user(db_session)
    org = make_org(db_session)
    db_session.add(
        OrganizationMembership(user=user, organization=org, role=OrganizationRole.VIEWER)
    )
    db_session.flush()

    # Delete in SQL so the database's ON DELETE CASCADE does the work, not the ORM.
    db_session.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org.id})

    remaining = db_session.scalar(select(func.count()).select_from(OrganizationMembership))
    assert remaining == 0
    assert db_session.get(User, user.id) is not None  # the user account itself survives
