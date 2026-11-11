"""Unit tests for the role -> permission matrix and slug generation."""

import pytest

from app.models import OrganizationRole
from app.security.authorization import ROLE_PERMISSIONS, Permission, role_has_permission
from app.services.organizations import slugify

ADMIN, MANAGER, VIEWER = (
    OrganizationRole.ORG_ADMIN,
    OrganizationRole.INTEGRATION_MANAGER,
    OrganizationRole.VIEWER,
)


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (VIEWER, Permission.ORG_READ, True),
        (VIEWER, Permission.MEMBERS_READ, True),
        (VIEWER, Permission.ORG_UPDATE, False),
        (VIEWER, Permission.MEMBERS_MANAGE, False),
        (MANAGER, Permission.ORG_READ, True),
        (MANAGER, Permission.MEMBERS_READ, True),
        (MANAGER, Permission.ORG_UPDATE, False),
        (MANAGER, Permission.MEMBERS_MANAGE, False),
        (ADMIN, Permission.ORG_READ, True),
        (ADMIN, Permission.MEMBERS_READ, True),
        (ADMIN, Permission.ORG_UPDATE, True),
        (ADMIN, Permission.MEMBERS_MANAGE, True),
    ],
)
def test_role_permission_matrix(
    role: OrganizationRole, permission: Permission, allowed: bool
) -> None:
    assert role_has_permission(role, permission) is allowed


def test_every_role_has_a_permission_set() -> None:
    assert set(ROLE_PERMISSIONS) == set(OrganizationRole)


def test_org_admin_holds_every_permission() -> None:
    assert ROLE_PERMISSIONS[ADMIN] == frozenset(Permission)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Acme Corp", "acme-corp"),
        ("  Acme   Corp (EU)  ", "acme-corp-eu"),
        ("\u00dcn\u00efcode & Co", "n-code-co"),  # accented letters are dropped
        ("!!!", "org"),
        ("a" * 80, "a" * 63),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert slugify(name) == expected
