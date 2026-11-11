"""Organizations (tenants) and organization memberships."""

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class OrganizationRole(enum.StrEnum):
    """Roles a user can hold inside one organization.

    Super Admin is deliberately not here: it is a platform-wide flag on the user
    (users.is_superadmin), not a role within a tenant.
    """

    ORG_ADMIN = "org_admin"
    INTEGRATION_MANAGER = "integration_manager"
    VIEWER = "viewer"


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        # URL-safe identifier: lowercase letters, digits and single hyphens.
        CheckConstraint(r"slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())

    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug}>"


class OrganizationMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        # A user has exactly one role per organization.
        UniqueConstraint("organization_id", "user_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # Indexed on its own for "which organizations does this user belong to?";
    # the unique constraint above already covers lookups by organization.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[OrganizationRole] = mapped_column(
        # Stored as VARCHAR + CHECK (not a native PG enum) so adding a role later is a
        # simple constraint change instead of an ALTER TYPE migration.
        Enum(
            OrganizationRole,
            name="organization_role",
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda roles: [role.value for role in roles],
        ),
        nullable=False,
    )

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")

    def __repr__(self) -> str:
        return (
            f"<OrganizationMembership user={self.user_id} org={self.organization_id} {self.role}>"
        )
