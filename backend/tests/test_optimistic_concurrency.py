"""Optimistic concurrency on employees: ETag / If-Match, 412 on stale edits."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, IntegrationEvent, Organization, OrganizationRole
from tests.factories import (
    add_member,
    auth_headers,
    create_employee,
    create_organization,
    create_user,
)


@pytest.fixture
def org(db_session: Session) -> Organization:
    return create_organization(db_session)


@pytest.fixture
def headers(db_session: Session, org: Organization) -> dict[str, str]:
    user = create_user(db_session)
    add_member(db_session, user, org, OrganizationRole.ORG_ADMIN)
    return auth_headers(user)


def url(org: Organization, *parts: object) -> str:
    return "/".join([f"/api/v1/organizations/{org.id}/employees", *map(str, parts)])


def count(session: Session, model: type, org: Organization) -> int:
    return session.scalar(
        select(func.count()).select_from(model).where(model.organization_id == org.id)
    )


def test_reads_and_writes_carry_the_version_as_etag(
    client: TestClient, db_session: Session, org: Organization, headers: dict[str, str]
) -> None:
    employee = create_employee(db_session, org)

    read = client.get(url(org, employee.id), headers=headers)
    changed = client.patch(
        url(org, employee.id),
        headers={**headers, "If-Match": read.headers["ETag"]},
        json={"designation": "Staff Engineer"},
    )

    assert (read.headers["ETag"], read.json()["version"]) == ('"1"', 1)
    assert changed.status_code == 200
    assert (changed.headers["ETag"], changed.json()["version"]) == ('"2"', 2)


def test_a_stale_edit_is_refused_and_changes_nothing(
    client: TestClient, db_session: Session, org: Organization, headers: dict[str, str]
) -> None:
    """Two admins open the same employee (version 1). The first saves; the second, still
    looking at version 1, must not silently overwrite the first one's change."""
    employee = create_employee(db_session, org, designation="Engineer")
    first = client.patch(
        url(org, employee.id), headers={**headers, "If-Match": '"1"'}, json={"location": "Pune"}
    )
    events_before = count(db_session, IntegrationEvent, org)
    audit_before = count(db_session, AuditLog, org)

    second = client.patch(
        url(org, employee.id),
        headers={**headers, "If-Match": '"1"'},
        json={"location": "Chennai", "designation": "Manager"},
    )

    assert first.status_code == 200
    assert second.status_code == 412
    error = second.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"] == {"expected_version": 1, "current_version": 2}
    now = client.get(url(org, employee.id), headers=headers).json()
    assert (now["location"], now["designation"], now["version"]) == ("Pune", "Engineer", 2)
    assert count(db_session, IntegrationEvent, org) == events_before  # no event
    assert count(db_session, AuditLog, org) == audit_before  # no audit entry


def test_without_if_match_the_last_write_wins_as_before(
    client: TestClient, db_session: Session, org: Organization, headers: dict[str, str]
) -> None:
    employee = create_employee(db_session, org)
    client.patch(url(org, employee.id), headers=headers, json={"location": "Pune"})

    response = client.patch(url(org, employee.id), headers=headers, json={"location": "Goa"})

    assert response.status_code == 200 and response.json()["version"] == 3


@pytest.mark.parametrize("value", ['W/"1"', "1", "*"])
def test_accepted_if_match_forms(
    client: TestClient, db_session: Session, org: Organization, headers: dict[str, str], value: str
) -> None:
    employee = create_employee(db_session, org)

    response = client.patch(
        url(org, employee.id), headers={**headers, "If-Match": value}, json={"location": "Pune"}
    )

    assert response.status_code == 200


def test_a_malformed_if_match_is_rejected(
    client: TestClient, db_session: Session, org: Organization, headers: dict[str, str]
) -> None:
    employee = create_employee(db_session, org)

    response = client.patch(
        url(org, employee.id), headers={**headers, "If-Match": '"abc"'}, json={"location": "X"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_if_match"


def test_a_change_that_changes_nothing_keeps_the_version(
    client: TestClient, db_session: Session, org: Organization, headers: dict[str, str]
) -> None:
    employee = create_employee(db_session, org, location="Pune")

    response = client.patch(url(org, employee.id), headers=headers, json={"location": "Pune"})

    assert response.json()["version"] == 1


def test_terminate_and_archive_honour_if_match(
    client: TestClient, db_session: Session, org: Organization, headers: dict[str, str]
) -> None:
    employee = create_employee(db_session, org)
    client.patch(url(org, employee.id), headers=headers, json={"location": "Pune"})  # v2

    stale = client.post(url(org, employee.id, "terminate"), headers={**headers, "If-Match": '"1"'})
    fresh = client.post(url(org, employee.id, "terminate"), headers={**headers, "If-Match": '"2"'})
    stale_archive = client.delete(url(org, employee.id), headers={**headers, "If-Match": '"2"'})
    archive = client.delete(url(org, employee.id), headers={**headers, "If-Match": '"3"'})

    assert stale.status_code == 412
    assert (fresh.status_code, fresh.headers["ETag"]) == (200, '"3"')
    assert stale_archive.status_code == 412
    assert archive.status_code == 204


def test_moving_direct_reports_changes_their_version(
    client: TestClient, db_session: Session, org: Organization, headers: dict[str, str]
) -> None:
    """A termination moves the reports to a new manager: an admin editing a report from
    a screen loaded before the termination gets 412, not a silent revert of the move."""
    boss = create_employee(db_session, org)
    report = create_employee(db_session, org, manager=boss)
    client.post(url(org, boss.id, "terminate"), headers=headers)

    response = client.patch(
        url(org, report.id), headers={**headers, "If-Match": '"1"'}, json={"location": "Goa"}
    )

    assert response.status_code == 412
    assert response.json()["error"]["details"]["current_version"] == 2


def test_create_returns_the_first_version(
    client: TestClient, db_session: Session, org: Organization, headers: dict[str, str]
) -> None:
    response = client.post(
        url(org),
        headers=headers,
        json={
            "employee_number": "E-1",
            "first_name": "A",
            "last_name": "B",
            "email": "a.b@acme.example",
            "joining_date": "2026-11-01",
        },
    )

    assert (response.status_code, response.headers["ETag"]) == (201, '"1"')
