"""API tests for /api/v1/organizations: CRUD, role permissions and tenant isolation."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationRole, User
from tests.factories import add_member, auth_headers, create_organization, create_user

ORGS = "/api/v1/organizations"
ADMIN = OrganizationRole.ORG_ADMIN
MANAGER = OrganizationRole.INTEGRATION_MANAGER
VIEWER = OrganizationRole.VIEWER


def org_with(session: Session, role: OrganizationRole, **kwargs: str) -> tuple[Organization, User]:
    """An organization plus one member holding `role`."""
    org = create_organization(session, **kwargs)
    user = create_user(session)
    add_member(session, user, org, role)
    return org, user


# ---- create --------------------------------------------------------------------------


def test_create_organization_makes_creator_admin(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session)

    response = client.post(ORGS, json={"name": "Acme Corp"}, headers=auth_headers(user))

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Corp"
    assert body["slug"] == "acme-corp"
    assert body["my_role"] == "org_admin"
    me = client.get("/api/v1/auth/me", headers=auth_headers(user)).json()
    assert me["memberships"][0]["role"] == "org_admin"


def test_create_with_explicit_slug_and_duplicate_slug(
    client: TestClient, db_session: Session
) -> None:
    headers = auth_headers(create_user(db_session))

    first = client.post(ORGS, json={"name": "Acme", "slug": "acme-eu"}, headers=headers)
    duplicate = client.post(ORGS, json={"name": "Other", "slug": "acme-eu"}, headers=headers)

    assert first.status_code == 201
    assert first.json()["slug"] == "acme-eu"
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "slug_taken"


def test_generated_slug_collision_gets_a_suffix(client: TestClient, db_session: Session) -> None:
    headers = auth_headers(create_user(db_session))

    first = client.post(ORGS, json={"name": "Globex"}, headers=headers).json()
    second = client.post(ORGS, json={"name": "Globex"}, headers=headers).json()

    assert first["slug"] == "globex"
    assert second["slug"].startswith("globex-")
    assert second["slug"] != first["slug"]


@pytest.mark.parametrize("bad_slug", ["Acme", "acme corp", "-acme", "acme--eu"])
def test_create_rejects_invalid_slug(
    client: TestClient, db_session: Session, bad_slug: str
) -> None:
    headers = auth_headers(create_user(db_session))

    response = client.post(ORGS, json={"name": "Acme", "slug": bad_slug}, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "slug"


def test_create_requires_authentication(client: TestClient) -> None:
    assert client.post(ORGS, json={"name": "Acme"}).status_code == 401


# ---- list ----------------------------------------------------------------------------


def test_list_shows_only_my_organizations(client: TestClient, db_session: Session) -> None:
    mine, me = org_with(db_session, VIEWER, name="Mine")
    create_organization(db_session, name="Someone Else's")

    response = client.get(ORGS, headers=auth_headers(me))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [org["id"] for org in body["items"]] == [str(mine.id)]
    assert body["items"][0]["my_role"] == "viewer"


def test_list_hides_deactivated_organizations_from_members(
    client: TestClient, db_session: Session
) -> None:
    org, member = org_with(db_session, ADMIN)
    org.is_active = False
    db_session.flush()

    assert client.get(ORGS, headers=auth_headers(member)).json()["total"] == 0


def test_superadmin_lists_all_organizations(client: TestClient, db_session: Session) -> None:
    create_organization(db_session, name="Alpha")
    create_organization(db_session, name="Beta")
    superadmin = create_user(db_session, is_superadmin=True)

    body = client.get(ORGS, headers=auth_headers(superadmin)).json()

    assert body["total"] == 2
    assert all(org["my_role"] is None for org in body["items"])


def test_list_is_paginated(client: TestClient, db_session: Session) -> None:
    user = create_user(db_session)
    for name in ["Alpha", "Bravo", "Charlie"]:
        add_member(db_session, user, create_organization(db_session, name=name), VIEWER)

    page = client.get(ORGS, params={"limit": 2, "offset": 1}, headers=auth_headers(user)).json()

    assert page["total"] == 3
    assert (page["limit"], page["offset"]) == (2, 1)
    assert [org["name"] for org in page["items"]] == ["Bravo", "Charlie"]


def test_list_rejects_out_of_range_limit(client: TestClient, db_session: Session) -> None:
    headers = auth_headers(create_user(db_session))

    assert client.get(ORGS, params={"limit": 0}, headers=headers).status_code == 422
    assert client.get(ORGS, params={"limit": 101}, headers=headers).status_code == 422


# ---- get / update: isolation and roles -----------------------------------------------


@pytest.mark.parametrize("role", [ADMIN, MANAGER, VIEWER])
def test_any_member_can_read_their_organization(
    client: TestClient, db_session: Session, role: OrganizationRole
) -> None:
    org, member = org_with(db_session, role)

    response = client.get(f"{ORGS}/{org.id}", headers=auth_headers(member))

    assert response.status_code == 200
    assert response.json()["my_role"] == role.value


def test_non_member_gets_404_not_403(client: TestClient, db_session: Session) -> None:
    other_org = create_organization(db_session)
    outsider = create_user(db_session)

    response = client.get(f"{ORGS}/{other_org.id}", headers=auth_headers(outsider))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "organization_not_found"


def test_unknown_and_malformed_organization_ids(client: TestClient, db_session: Session) -> None:
    headers = auth_headers(create_user(db_session))

    assert client.get(f"{ORGS}/{uuid.uuid4()}", headers=headers).status_code == 404
    assert client.get(f"{ORGS}/not-a-uuid", headers=headers).status_code == 422


def test_superadmin_can_read_any_organization(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    superadmin = create_user(db_session, is_superadmin=True)

    response = client.get(f"{ORGS}/{org.id}", headers=auth_headers(superadmin))

    assert response.status_code == 200
    assert response.json()["my_role"] is None


def test_admin_can_rename_organization(client: TestClient, db_session: Session) -> None:
    org, admin = org_with(db_session, ADMIN, name="Old Name")

    response = client.patch(
        f"{ORGS}/{org.id}", json={"name": "New Name"}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


@pytest.mark.parametrize("role", [MANAGER, VIEWER])
def test_non_admin_members_cannot_rename(
    client: TestClient, db_session: Session, role: OrganizationRole
) -> None:
    org, member = org_with(db_session, role)

    response = client.patch(f"{ORGS}/{org.id}", json={"name": "X"}, headers=auth_headers(member))

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "insufficient_role"
    assert error["details"] == {"required_permission": "org:update"}


def test_admin_of_one_org_cannot_touch_another(client: TestClient, db_session: Session) -> None:
    _, admin_a = org_with(db_session, ADMIN, name="Org A")
    org_b, member_b = org_with(db_session, VIEWER, name="Org B")
    headers = auth_headers(admin_a)

    responses = [
        client.get(f"{ORGS}/{org_b.id}", headers=headers),
        client.patch(f"{ORGS}/{org_b.id}", json={"name": "Hacked"}, headers=headers),
        client.get(f"{ORGS}/{org_b.id}/members", headers=headers),
        client.post(
            f"{ORGS}/{org_b.id}/members",
            json={"email": "x@example.com", "role": "viewer"},
            headers=headers,
        ),
        client.patch(
            f"{ORGS}/{org_b.id}/members/{member_b.id}", json={"role": "org_admin"}, headers=headers
        ),
        client.delete(f"{ORGS}/{org_b.id}/members/{member_b.id}", headers=headers),
    ]

    assert [r.status_code for r in responses] == [404] * 6
    db_session.refresh(org_b)
    assert org_b.name == "Org B"


def test_member_of_deactivated_org_gets_404(client: TestClient, db_session: Session) -> None:
    org, admin = org_with(db_session, ADMIN)
    org.is_active = False
    db_session.flush()

    assert client.get(f"{ORGS}/{org.id}", headers=auth_headers(admin)).status_code == 404


# ---- members -------------------------------------------------------------------------


def test_viewer_can_list_members(client: TestClient, db_session: Session) -> None:
    org, viewer = org_with(db_session, VIEWER)
    admin = create_user(db_session, full_name="Alice Admin")
    add_member(db_session, admin, org, ADMIN)

    body = client.get(f"{ORGS}/{org.id}/members", headers=auth_headers(viewer)).json()

    assert body["total"] == 2
    assert {m["role"] for m in body["items"]} == {"viewer", "org_admin"}
    assert "password_hash" not in str(body)


def test_admin_adds_member_by_email(client: TestClient, db_session: Session) -> None:
    org, admin = org_with(db_session, ADMIN)
    newcomer = create_user(db_session, email="new.hire@acme.example")

    response = client.post(
        f"{ORGS}/{org.id}/members",
        json={"email": "New.Hire@acme.example", "role": "integration_manager"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == str(newcomer.id)
    assert response.json()["role"] == "integration_manager"


def test_add_member_errors(client: TestClient, db_session: Session) -> None:
    org, admin = org_with(db_session, ADMIN)
    existing = create_user(db_session)
    add_member(db_session, existing, org, VIEWER)
    headers = auth_headers(admin)

    duplicate = client.post(
        f"{ORGS}/{org.id}/members",
        json={"email": existing.email, "role": "viewer"},
        headers=headers,
    )
    unknown = client.post(
        f"{ORGS}/{org.id}/members",
        json={"email": "ghost@example.com", "role": "viewer"},
        headers=headers,
    )
    bad_role = client.post(
        f"{ORGS}/{org.id}/members", json={"email": existing.email, "role": "owner"}, headers=headers
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "already_member"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "user_not_found"
    assert bad_role.status_code == 422


@pytest.mark.parametrize("role", [MANAGER, VIEWER])
def test_non_admins_cannot_manage_members(
    client: TestClient, db_session: Session, role: OrganizationRole
) -> None:
    org, member = org_with(db_session, role)
    target = create_user(db_session)

    response = client.post(
        f"{ORGS}/{org.id}/members",
        json={"email": target.email, "role": "org_admin"},
        headers=auth_headers(member),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


def test_admin_changes_role_and_removes_member(client: TestClient, db_session: Session) -> None:
    org, admin = org_with(db_session, ADMIN)
    member = create_user(db_session)
    add_member(db_session, member, org, VIEWER)
    headers = auth_headers(admin)

    promoted = client.patch(
        f"{ORGS}/{org.id}/members/{member.id}",
        json={"role": "integration_manager"},
        headers=headers,
    )
    removed = client.delete(f"{ORGS}/{org.id}/members/{member.id}", headers=headers)
    removed_again = client.delete(f"{ORGS}/{org.id}/members/{member.id}", headers=headers)

    assert promoted.status_code == 200
    assert promoted.json()["role"] == "integration_manager"
    assert removed.status_code == 204
    assert removed_again.status_code == 404
    assert removed_again.json()["error"]["code"] == "member_not_found"


def test_last_admin_cannot_be_demoted_or_removed(client: TestClient, db_session: Session) -> None:
    org, admin = org_with(db_session, ADMIN)
    headers = auth_headers(admin)

    demote = client.patch(
        f"{ORGS}/{org.id}/members/{admin.id}", json={"role": "viewer"}, headers=headers
    )
    remove = client.delete(f"{ORGS}/{org.id}/members/{admin.id}", headers=headers)

    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "last_admin"
    assert remove.status_code == 409
    assert remove.json()["error"]["code"] == "last_admin"


def test_admin_can_step_down_when_another_admin_exists(
    client: TestClient, db_session: Session
) -> None:
    org, admin = org_with(db_session, ADMIN)
    add_member(db_session, create_user(db_session), org, ADMIN)

    response = client.patch(
        f"{ORGS}/{org.id}/members/{admin.id}", json={"role": "viewer"}, headers=auth_headers(admin)
    )

    assert response.status_code == 200
    assert response.json()["role"] == "viewer"


def test_member_lost_access_after_removal(client: TestClient, db_session: Session) -> None:
    org, admin = org_with(db_session, ADMIN)
    member = create_user(db_session)
    add_member(db_session, member, org, VIEWER)
    member_headers = auth_headers(member)
    assert client.get(f"{ORGS}/{org.id}", headers=member_headers).status_code == 200

    client.delete(f"{ORGS}/{org.id}/members/{member.id}", headers=auth_headers(admin))

    assert client.get(f"{ORGS}/{org.id}", headers=member_headers).status_code == 404
