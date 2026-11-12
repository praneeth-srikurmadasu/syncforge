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
        # Phase 3: every member reads employees/departments; only admins change them.
        (VIEWER, Permission.EMPLOYEES_READ, True),
        (VIEWER, Permission.DEPARTMENTS_READ, True),
        (VIEWER, Permission.EMPLOYEES_WRITE, False),
        (VIEWER, Permission.DEPARTMENTS_MANAGE, False),
        (MANAGER, Permission.EMPLOYEES_READ, True),
        (MANAGER, Permission.DEPARTMENTS_READ, True),
        (MANAGER, Permission.EMPLOYEES_WRITE, False),
        (MANAGER, Permission.DEPARTMENTS_MANAGE, False),
        (ADMIN, Permission.EMPLOYEES_WRITE, True),
        (ADMIN, Permission.DEPARTMENTS_MANAGE, True),
        # Phase 4: everyone sees connectors; integration managers and admins manage them.
        (VIEWER, Permission.CONNECTORS_READ, True),
        (VIEWER, Permission.CONNECTORS_MANAGE, False),
        (MANAGER, Permission.CONNECTORS_READ, True),
        (MANAGER, Permission.CONNECTORS_MANAGE, True),
        (ADMIN, Permission.CONNECTORS_MANAGE, True),
        # Phase 5: everyone sees workflows and events; integration managers and admins
        # configure workflows.
        (VIEWER, Permission.WORKFLOWS_READ, True),
        (VIEWER, Permission.EVENTS_READ, True),
        (VIEWER, Permission.WORKFLOWS_MANAGE, False),
        (MANAGER, Permission.WORKFLOWS_MANAGE, True),
        (MANAGER, Permission.EVENTS_READ, True),
        (MANAGER, Permission.EMPLOYEES_WRITE, False),
        (ADMIN, Permission.WORKFLOWS_MANAGE, True),
        # Phase 6: replaying dead-lettered events makes real external calls.
        (VIEWER, Permission.EVENTS_REPLAY, False),
        (MANAGER, Permission.EVENTS_REPLAY, True),
        (ADMIN, Permission.EVENTS_REPLAY, True),
        # Phase 7: the audit log shows other people's actions and permission changes.
        (VIEWER, Permission.AUDIT_READ, False),
        (MANAGER, Permission.AUDIT_READ, True),
        (ADMIN, Permission.AUDIT_READ, True),
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
