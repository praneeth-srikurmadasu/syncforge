"""Organization and membership endpoints: /api/v1/organizations/*

Every route under /{organization_id} goes through `require_org_permission`, which
enforces tenant isolation (non-members get 404) and role permissions (403).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import CurrentUser, DbSession, require_org_permission
from app.models import Organization, OrganizationMembership, OrganizationRole
from app.repositories.organizations import OrganizationRepository
from app.schemas.common import Limit, Offset, Page
from app.schemas.organizations import (
    MemberCreate,
    MemberResponse,
    MemberUpdate,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.security.authorization import OrgContext, Permission
from app.services.organizations import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])

CanReadOrg = Annotated[OrgContext, Depends(require_org_permission(Permission.ORG_READ))]
CanUpdateOrg = Annotated[OrgContext, Depends(require_org_permission(Permission.ORG_UPDATE))]
CanReadMembers = Annotated[OrgContext, Depends(require_org_permission(Permission.MEMBERS_READ))]
CanManageMembers = Annotated[OrgContext, Depends(require_org_permission(Permission.MEMBERS_MANAGE))]

_ORG_ERRORS = {
    401: {"description": "Not authenticated"},
    403: {"description": "Member, but role lacks the required permission"},
    404: {"description": "Organization does not exist or caller is not a member"},
}


def _org_response(
    organization: Organization, my_role: OrganizationRole | None
) -> OrganizationResponse:
    return OrganizationResponse.model_validate(organization).model_copy(update={"my_role": my_role})


def _member_response(membership: OrganizationMembership) -> MemberResponse:
    return MemberResponse(
        user_id=membership.user_id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


# ---- organizations -------------------------------------------------------------------


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"description": "Not authenticated"}, 409: {"description": "Slug taken"}},
)
def create_organization(
    payload: OrganizationCreate, user: CurrentUser, db: DbSession
) -> OrganizationResponse:
    """Create an organization. The caller becomes its first Organization Admin."""
    organization = OrganizationService(db).create(
        creator=user, name=payload.name, slug=payload.slug
    )
    return _org_response(organization, OrganizationRole.ORG_ADMIN)


@router.get("", response_model=Page[OrganizationResponse])
def list_organizations(
    user: CurrentUser, db: DbSession, limit: Limit = 20, offset: Offset = 0
) -> Page[OrganizationResponse]:
    """Organizations the caller belongs to. A Super Admin sees every organization."""
    repository = OrganizationRepository(db)
    if user.is_superadmin:
        organizations, total = repository.list_all(limit=limit, offset=offset)
    else:
        organizations, total = repository.list_for_user(user.id, limit=limit, offset=offset)
    roles = repository.roles_for_user(user.id, [org.id for org in organizations])
    return Page(
        items=[_org_response(org, roles.get(org.id)) for org in organizations],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{organization_id}", response_model=OrganizationResponse, responses=_ORG_ERRORS)
def get_organization(access: CanReadOrg) -> OrganizationResponse:
    return _org_response(access.organization, access.role)


@router.patch("/{organization_id}", response_model=OrganizationResponse, responses=_ORG_ERRORS)
def update_organization(
    payload: OrganizationUpdate, access: CanUpdateOrg, db: DbSession
) -> OrganizationResponse:
    """Rename the organization (Organization Admin)."""
    organization = OrganizationService(db).rename(access.organization, name=payload.name)
    return _org_response(organization, access.role)


# ---- members -------------------------------------------------------------------------


@router.get(
    "/{organization_id}/members", response_model=Page[MemberResponse], responses=_ORG_ERRORS
)
def list_members(
    access: CanReadMembers, db: DbSession, limit: Limit = 20, offset: Offset = 0
) -> Page[MemberResponse]:
    memberships, total = OrganizationRepository(db).list_members(
        access.organization.id, limit=limit, offset=offset
    )
    return Page(
        items=[_member_response(m) for m in memberships], total=total, limit=limit, offset=offset
    )


@router.post(
    "/{organization_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ORG_ERRORS | {409: {"description": "Already a member"}},
)
def add_member(payload: MemberCreate, access: CanManageMembers, db: DbSession) -> MemberResponse:
    """Add an existing user to the organization with a role (Organization Admin)."""
    membership = OrganizationService(db).add_member(
        access.organization, email=payload.email, role=payload.role
    )
    return _member_response(membership)


@router.patch(
    "/{organization_id}/members/{user_id}",
    response_model=MemberResponse,
    responses=_ORG_ERRORS | {409: {"description": "Would remove the last Organization Admin"}},
)
def change_member_role(
    user_id: uuid.UUID, payload: MemberUpdate, access: CanManageMembers, db: DbSession
) -> MemberResponse:
    membership = OrganizationService(db).change_role(
        access.organization, user_id=user_id, role=payload.role
    )
    return _member_response(membership)


@router.delete(
    "/{organization_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ORG_ERRORS | {409: {"description": "Would remove the last Organization Admin"}},
)
def remove_member(user_id: uuid.UUID, access: CanManageMembers, db: DbSession) -> Response:
    OrganizationService(db).remove_member(access.organization, user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
