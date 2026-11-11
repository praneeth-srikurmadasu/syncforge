"""Organization and membership data access."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Organization, OrganizationMembership, OrganizationRole, User


class OrganizationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---- organizations -------------------------------------------------------------

    def get(self, organization_id: uuid.UUID) -> Organization | None:
        return self.session.get(Organization, organization_id)

    def slug_exists(self, slug: str) -> bool:
        return (
            self.session.scalar(select(Organization.id).where(Organization.slug == slug))
            is not None
        )

    def add(self, organization: Organization) -> Organization:
        self.session.add(organization)
        self.session.flush()
        return organization

    def list_all(self, *, limit: int, offset: int) -> tuple[list[Organization], int]:
        total = self.session.scalar(select(func.count()).select_from(Organization)) or 0
        items = self.session.scalars(
            select(Organization)
            .order_by(Organization.name, Organization.id)
            .limit(limit)
            .offset(offset)
        )
        return list(items), total

    def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Organization], int]:
        """Active organizations the user is a member of - the tenant isolation boundary."""
        condition = (
            select(Organization)
            .join(OrganizationMembership)
            .where(OrganizationMembership.user_id == user_id, Organization.is_active.is_(True))
        )
        total = self.session.scalar(select(func.count()).select_from(condition.subquery())) or 0
        items = self.session.scalars(
            condition.order_by(Organization.name, Organization.id).limit(limit).offset(offset)
        )
        return list(items), total

    # ---- memberships ---------------------------------------------------------------

    def get_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationMembership | None:
        return self.session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == user_id,
            )
        )

    def roles_for_user(
        self, user_id: uuid.UUID, organization_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, OrganizationRole]:
        if not organization_ids:
            return {}
        rows = self.session.execute(
            select(OrganizationMembership.organization_id, OrganizationMembership.role).where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.organization_id.in_(organization_ids),
            )
        )
        return {org_id: role for org_id, role in rows}

    def add_membership(self, membership: OrganizationMembership) -> OrganizationMembership:
        self.session.add(membership)
        self.session.flush()
        return membership

    def list_members(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[OrganizationMembership], int]:
        condition = OrganizationMembership.organization_id == organization_id
        total = (
            self.session.scalar(
                select(func.count()).select_from(OrganizationMembership).where(condition)
            )
            or 0
        )
        items = self.session.scalars(
            select(OrganizationMembership)
            .join(OrganizationMembership.user)
            .options(joinedload(OrganizationMembership.user))
            .where(condition)
            .order_by(User.full_name, User.id)
            .limit(limit)
            .offset(offset)
        )
        return list(items), total

    def lock_admin_memberships(self, organization_id: uuid.UUID) -> list[OrganizationMembership]:
        """Lock the organization's admin rows (SELECT ... FOR UPDATE).

        Used before demoting or removing an admin. Two concurrent requests that each
        try to remove "the other" admin are serialized here, so the organization can
        never be left with zero admins.
        """
        return list(
            self.session.scalars(
                select(OrganizationMembership)
                .where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.role == OrganizationRole.ORG_ADMIN,
                )
                .order_by(OrganizationMembership.id)
                .with_for_update()
            )
        )

    def delete_membership(self, membership: OrganizationMembership) -> None:
        self.session.delete(membership)
        self.session.flush()
