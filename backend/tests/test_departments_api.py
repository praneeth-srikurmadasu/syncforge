"""API tests for /api/v1/organizations/{id}/departments."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Organization, OrganizationRole, User
from tests.factories import (
    add_member,
    auth_headers,
    create_department,
    create_employee,
    create_organization,
    create_user,
)

ADMIN = OrganizationRole.ORG_ADMIN
MANAGER = OrganizationRole.INTEGRATION_MANAGER
VIEWER = OrganizationRole.VIEWER


def url(org: Organization, *parts: object) -> str:
    return "/".join([f"/api/v1/organizations/{org.id}/departments", *map(str, parts)]).rstrip("/")


def member(session: Session, org: Organization, role: OrganizationRole) -> dict[str, str]:
    user: User = create_user(session)
    add_member(session, user, org, role)
    return auth_headers(user)


def test_admin_creates_lists_renames_and_deletes(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    headers = member(db_session, org, ADMIN)

    created = client.post(url(org), json={"name": "  Engineering "}, headers=headers)
    assert created.status_code == 201
    department_id = created.json()["id"]
    assert created.json()["name"] == "Engineering"  # whitespace trimmed
    assert created.json()["employee_count"] == 0

    renamed = client.patch(url(org, department_id), json={"name": "Platform"}, headers=headers)
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Platform"

    listing = client.get(url(org), headers=headers).json()
    assert [d["name"] for d in listing["items"]] == ["Platform"]

    assert client.delete(url(org, department_id), headers=headers).status_code == 204
    assert client.get(url(org), headers=headers).json()["total"] == 0


def test_list_is_sorted_and_reports_employee_counts(
    client: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    sales = create_department(db_session, org, "sales")
    create_department(db_session, org, "Engineering")
    create_employee(db_session, org, department=sales)
    create_employee(db_session, org, department=sales)

    body = client.get(url(org), headers=member(db_session, org, VIEWER)).json()

    assert [(d["name"], d["employee_count"]) for d in body["items"]] == [
        ("Engineering", 0),
        ("sales", 2),
    ]


def test_duplicate_name_ignoring_case_is_409(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    create_department(db_session, org, "Engineering")
    other = create_department(db_session, org, "Sales")
    headers = member(db_session, org, ADMIN)

    create = client.post(url(org), json={"name": "ENGINEERING"}, headers=headers)
    rename = client.patch(url(org, other.id), json={"name": "engineering"}, headers=headers)

    assert create.status_code == 409
    assert create.json()["error"]["code"] == "department_name_taken"
    assert rename.status_code == 409


def test_rename_to_same_name_with_different_case_is_allowed(
    client: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    dept = create_department(db_session, org, "engineering")

    response = client.patch(
        url(org, dept.id), json={"name": "Engineering"}, headers=member(db_session, org, ADMIN)
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Engineering"


def test_department_with_employees_cannot_be_deleted(
    client: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    dept = create_department(db_session, org, "Sales")
    create_employee(db_session, org, department=dept)

    response = client.delete(url(org, dept.id), headers=member(db_session, org, ADMIN))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "department_in_use"
    assert response.json()["error"]["details"] == {"employee_count": 1}


@pytest.mark.parametrize("role", [MANAGER, VIEWER])
def test_non_admin_roles_can_read_but_not_manage(
    client: TestClient, db_session: Session, role: OrganizationRole
) -> None:
    org = create_organization(db_session)
    dept = create_department(db_session, org, "Sales")
    headers = member(db_session, org, role)

    assert client.get(url(org), headers=headers).status_code == 200
    for response in (
        client.post(url(org), json={"name": "X"}, headers=headers),
        client.patch(url(org, dept.id), json={"name": "Y"}, headers=headers),
        client.delete(url(org, dept.id), headers=headers),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "insufficient_role"


def test_other_organizations_departments_are_invisible(
    client: TestClient, db_session: Session
) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    globex_sales = create_department(db_session, globex, "Sales")
    acme_admin = member(db_session, acme, ADMIN)

    # Through their own organization's URL: the foreign department ID is unknown.
    assert (
        client.patch(
            url(acme, globex_sales.id), json={"name": "Hacked"}, headers=acme_admin
        ).status_code
        == 404
    )
    assert client.delete(url(acme, globex_sales.id), headers=acme_admin).status_code == 404
    # Through the other organization's URL: the organization itself is hidden.
    response = client.get(url(globex), headers=acme_admin)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "organization_not_found"


def test_unknown_department_is_404(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)

    response = client.delete(url(org, uuid.uuid4()), headers=member(db_session, org, ADMIN))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "department_not_found"


def test_requires_authentication(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)

    assert client.get(url(org)).status_code == 401
