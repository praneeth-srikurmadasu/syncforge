"""Role-based access control (RBAC) and organization isolation.

Model
-----
* A user acts inside an organization through a membership that carries one role.
* Each role grants a fixed set of permissions (ROLE_PERMISSIONS). Endpoints ask for
  a permission, never for a role, so adding a role or permission is a one-line change.
* Super Admin (users.is_superadmin) is platform-wide and holds every permission in
  every organization, even without a membership.

Isolation rule
--------------
If the caller is not a member of the organization (and not a Super Admin), the
organization is reported as **404 Not Found**, not 403 - so an outsider cannot even
learn that an organization ID exists. A member who lacks a permission gets 403.
"""

import enum
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, PermissionDeniedError
from app.models import Organization, OrganizationRole, User
from app.repositories.organizations import OrganizationRepository


class Permission(enum.StrEnum):
    ORG_READ = "org:read"
    ORG_UPDATE = "org:update"
    MEMBERS_READ = "members:read"
    MEMBERS_MANAGE = "members:manage"
    EMPLOYEES_READ = "employees:read"
    EMPLOYEES_WRITE = "employees:write"
    DEPARTMENTS_READ = "departments:read"
    DEPARTMENTS_MANAGE = "departments:manage"


_VIEWER = frozenset(
    {
        Permission.ORG_READ,
        Permission.MEMBERS_READ,
        Permission.EMPLOYEES_READ,
        Permission.DEPARTMENTS_READ,
    }
)

ROLE_PERMISSIONS: dict[OrganizationRole, frozenset[Permission]] = {
    OrganizationRole.VIEWER: _VIEWER,
    # Integration managers gain connector/workflow permissions in Phases 4-5.
    OrganizationRole.INTEGRATION_MANAGER: _VIEWER,
    OrganizationRole.ORG_ADMIN: frozenset(Permission),
}


def role_has_permission(role: OrganizationRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]


@dataclass(frozen=True)
class OrgContext:
    """The result of a successful access check, handed to the endpoint."""

    organization: Organization
    user: User
    role: OrganizationRole | None  # None: a Super Admin acting without a membership

    def can(self, permission: Permission) -> bool:
        if self.user.is_superadmin:
            return True
        return self.role is not None and role_has_permission(self.role, permission)


def resolve_org_access(
    session: Session, user: User, organization_id: uuid.UUID, permission: Permission
) -> OrgContext:
    """Load the organization and enforce isolation plus the required permission."""
    organizations = OrganizationRepository(session)
    organization = organizations.get(organization_id)
    membership = organizations.get_membership(organization_id, user.id) if organization else None

    visible = organization is not None and (
        user.is_superadmin or (membership is not None and organization.is_active)
    )
    if not visible:
        raise NotFoundError("Organization not found.", code="organization_not_found")

    context = OrgContext(
        organization=organization,  # type: ignore[arg-type]  # checked by `visible`
        user=user,
        role=membership.role if membership else None,
    )
    if not context.can(permission):
        raise PermissionDeniedError(
            "Your role does not allow this action.",
            code="insufficient_role",
            details={"required_permission": permission.value},
        )
    return context
