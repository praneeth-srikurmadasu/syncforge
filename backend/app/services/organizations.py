"""Organization and membership use cases.

Authorization (who may call what) is enforced before these methods run, by the
`require_org_permission` dependency. This service enforces the business rules:
unique slugs, one membership per user, and "an organization always keeps at least
one Organization Admin".
"""

import logging
import re
import secrets
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.core.errors import ConflictError, NotFoundError
from app.models import Organization, OrganizationMembership, OrganizationRole, User
from app.repositories.organizations import OrganizationRepository
from app.repositories.users import UserRepository

logger = logging.getLogger("syncforge.organizations")

SLUG_MAX_LENGTH = 63


def slugify(name: str) -> str:
    """'Acme Corp (EU)' -> 'acme-corp-eu'. Falls back to 'org' if nothing is left."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:SLUG_MAX_LENGTH].rstrip("-") or "org"


class OrganizationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.organizations = OrganizationRepository(session)
        self.users = UserRepository(session)

    # ---- organizations -------------------------------------------------------------

    def create(self, *, creator: User, name: str, slug: str | None) -> Organization:
        """Create an organization; the creator becomes its first Organization Admin."""
        if slug is not None:
            if self.organizations.slug_exists(slug):
                raise ConflictError("This slug is already in use.", code="slug_taken")
        else:
            slug = self._unique_slug_from(name)

        organization = Organization(name=name, slug=slug)
        try:
            self.organizations.add(organization)
            self.organizations.add_membership(
                OrganizationMembership(
                    organization=organization, user=creator, role=OrganizationRole.ORG_ADMIN
                )
            )
            self.session.flush()
            audit.record(
                self.session,
                organization_id=organization.id,
                action="organization.created",
                resource_type="organization",
                resource_id=organization.id,
                details={"name": name, "slug": slug, "admin_user_id": creator.id},
            )
            self.session.commit()
        except IntegrityError as exc:
            # A concurrent request claimed the same slug between our check and insert.
            self.session.rollback()
            raise ConflictError("This slug is already in use.", code="slug_taken") from exc

        logger.info(
            "organization created",
            extra={"organization_id": str(organization.id), "user_id": str(creator.id)},
        )
        return organization

    def rename(self, organization: Organization, *, name: str) -> Organization:
        previous = organization.name
        organization.name = name
        audit.record(
            self.session,
            organization_id=organization.id,
            action="organization.renamed",
            resource_type="organization",
            resource_id=organization.id,
            details={"from": previous, "to": name},
        )
        self.session.commit()
        return organization

    def _unique_slug_from(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        while self.organizations.slug_exists(candidate):
            suffix = secrets.token_hex(3)  # e.g. "acme-corp-4f9a1c"
            candidate = f"{base[: SLUG_MAX_LENGTH - len(suffix) - 1]}-{suffix}"
        return candidate

    # ---- memberships ---------------------------------------------------------------

    def add_member(
        self, organization: Organization, *, email: str, role: OrganizationRole
    ) -> OrganizationMembership:
        user = self.users.get_by_email(email)
        if user is None or not user.is_active:
            raise NotFoundError("No active user with this email.", code="user_not_found")
        if self.organizations.get_membership(organization.id, user.id) is not None:
            raise ConflictError("User is already a member.", code="already_member")

        membership = OrganizationMembership(organization=organization, user=user, role=role)
        try:
            self.organizations.add_membership(membership)
            self._audit_member(organization, "member.added", user.id, {"role": role})
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("User is already a member.", code="already_member") from exc

        logger.info(
            "member added",
            extra={
                "organization_id": str(organization.id),
                "user_id": str(user.id),
                "role": role.value,
            },
        )
        return membership

    def change_role(
        self, organization: Organization, *, user_id: uuid.UUID, role: OrganizationRole
    ) -> OrganizationMembership:
        membership = self._get_member(organization, user_id)
        if membership.role == OrganizationRole.ORG_ADMIN and role != OrganizationRole.ORG_ADMIN:
            self._ensure_another_admin_remains(organization, membership)
        previous = membership.role
        membership.role = role
        self._audit_member(
            organization, "member.role_changed", user_id, {"from_role": previous, "to_role": role}
        )
        self.session.commit()
        logger.info(
            "member role changed",
            extra={
                "organization_id": str(organization.id),
                "user_id": str(user_id),
                "from_role": previous.value,
                "to_role": role.value,
            },
        )
        return membership

    def remove_member(self, organization: Organization, *, user_id: uuid.UUID) -> None:
        membership = self._get_member(organization, user_id)
        if membership.role == OrganizationRole.ORG_ADMIN:
            self._ensure_another_admin_remains(organization, membership)
        role = membership.role
        self.organizations.delete_membership(membership)
        self._audit_member(organization, "member.removed", user_id, {"role": role})
        self.session.commit()
        logger.info(
            "member removed",
            extra={"organization_id": str(organization.id), "user_id": str(user_id)},
        )

    def _audit_member(
        self, organization: Organization, action: str, user_id: uuid.UUID, details: dict
    ) -> None:
        """Permission changes are audited: who gave or took which role from whom."""
        audit.record(
            self.session,
            organization_id=organization.id,
            action=action,
            resource_type="membership",
            resource_id=user_id,
            details={"user_id": user_id, **details},
        )

    def _get_member(self, organization: Organization, user_id: uuid.UUID) -> OrganizationMembership:
        membership = self.organizations.get_membership(organization.id, user_id)
        if membership is None:
            raise NotFoundError("Member not found.", code="member_not_found")
        return membership

    def _ensure_another_admin_remains(
        self, organization: Organization, leaving: OrganizationMembership
    ) -> None:
        admins = self.organizations.lock_admin_memberships(organization.id)
        if not any(admin.id != leaving.id for admin in admins):
            # No explicit rollback: the request's session is rolled back when it
            # closes, which also releases the row locks taken above.
            raise ConflictError(
                "An organization must keep at least one Organization Admin.", code="last_admin"
            )
