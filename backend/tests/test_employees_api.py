"""API tests for /api/v1/organizations/{id}/employees: CRUD, search, lifecycle and isolation."""

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import EmploymentStatus, Organization, OrganizationRole
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
    return "/".join([f"/api/v1/organizations/{org.id}/employees", *map(str, parts)])


def member(session: Session, org: Organization, role: OrganizationRole = ADMIN) -> dict[str, str]:
    user = create_user(session)
    add_member(session, user, org, role)
    return auth_headers(user)


def new_employee(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "employee_number": "E-1001",
        "first_name": "Grace",
        "last_name": "Hopper",
        "email": "Grace.Hopper@Acme.example",
        "designation": "Staff Engineer",
        "location": "Bengaluru",
        "joining_date": "2024-01-15",
    }
    body.update(overrides)
    return body


@pytest.fixture
def events(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Captures log records so tests can assert on the lifecycle events emitted."""
    caplog.set_level(logging.INFO, logger="syncforge.employees")
    return caplog


def emitted(caplog: pytest.LogCaptureFixture) -> list[tuple[str, str, list[str]]]:
    return [
        (r.event_type, r.employee_id, r.changed_fields)  # type: ignore[attr-defined]
        for r in caplog.records
        if r.getMessage() == "employee lifecycle event"
    ]


# ---- create --------------------------------------------------------------------------


def test_create_employee(
    client: TestClient, db_session: Session, events: pytest.LogCaptureFixture
) -> None:
    org = create_organization(db_session)
    dept = create_department(db_session, org, "Engineering")
    boss = create_employee(db_session, org, first_name="Ada", last_name="Lovelace")

    response = client.post(
        url(org),
        json=new_employee(department_id=str(dept.id), manager_id=str(boss.id)),
        headers=member(db_session, org),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "grace.hopper@acme.example"  # normalized to lower case
    assert body["full_name"] == "Grace Hopper"
    assert body["employment_status"] == "active"
    assert body["department"] == {"id": str(dept.id), "name": "Engineering"}
    assert body["manager"]["full_name"] == "Ada Lovelace"
    assert body["organization_id"] == str(org.id)
    assert body["termination_date"] is None and body["archived_at"] is None

    [(event_type, employee_id, fields)] = emitted(events)
    assert (event_type, employee_id) == ("employee.created", body["id"])
    assert "email" in fields
    # The log carries field names only, never personal data.
    assert all("grace" not in str(vars(record)).lower() for record in events.records)


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"email": "not-an-email"}, "email"),
        ({"first_name": "   "}, "first_name"),
        ({"employee_number": "has spaces"}, "employee_number"),
        ({"employment_status": "terminated"}, "employment_status"),
        ({"joining_date": "15/01/2024"}, "joining_date"),
        ({"last_name": "x" * 101}, "last_name"),
    ],
)
def test_create_rejects_invalid_input(
    client: TestClient, db_session: Session, override: dict[str, str], field: str
) -> None:
    org = create_organization(db_session)

    response = client.post(url(org), json=new_employee(**override), headers=member(db_session, org))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert any(d["field"] == field for d in response.json()["error"]["details"])


def test_create_requires_mandatory_fields(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)

    response = client.post(url(org), json={}, headers=member(db_session, org))

    fields = {d["field"] for d in response.json()["error"]["details"]}
    assert response.status_code == 422
    assert {"employee_number", "first_name", "last_name", "email", "joining_date"} <= fields


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"employee_number": "E-1"}, "employee_number_taken"),
        ({"email": "SAM@acme.example"}, "email_taken"),  # case-insensitive
    ],
)
def test_create_rejects_duplicates(
    client: TestClient, db_session: Session, override: dict[str, str], code: str
) -> None:
    org = create_organization(db_session)
    create_employee(db_session, org, employee_number="E-1", email="sam@acme.example")

    response = client.post(url(org), json=new_employee(**override), headers=member(db_session, org))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code


def test_create_rejects_references_into_another_organization(
    client: TestClient, db_session: Session
) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    globex_dept = create_department(db_session, globex, "Sales")
    globex_boss = create_employee(db_session, globex)
    headers = member(db_session, acme)

    dept = client.post(
        url(acme), json=new_employee(department_id=str(globex_dept.id)), headers=headers
    )
    boss = client.post(
        url(acme), json=new_employee(manager_id=str(globex_boss.id)), headers=headers
    )

    assert dept.status_code == 422 and dept.json()["error"]["code"] == "department_not_found"
    assert boss.status_code == 422 and boss.json()["error"]["code"] == "manager_not_found"


def test_create_rejects_terminated_manager(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    gone = create_employee(
        db_session,
        org,
        employment_status=EmploymentStatus.TERMINATED,
        termination_date=date(2025, 1, 31),
    )

    response = client.post(
        url(org), json=new_employee(manager_id=str(gone.id)), headers=member(db_session, org)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "manager_terminated"


# ---- read and list -------------------------------------------------------------------


def test_get_employee_and_unknown_id(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)
    headers = member(db_session, org, VIEWER)

    assert client.get(url(org, employee.id), headers=headers).json()["id"] == str(employee.id)
    missing = client.get(url(org, uuid.uuid4()), headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "employee_not_found"


def test_pagination_is_stable_and_complete(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    for i in range(7):
        create_employee(db_session, org, last_name="Same", first_name=f"P{i}")
    headers = member(db_session, org, VIEWER)

    pages = [
        client.get(url(org), params={"limit": 3, "offset": o}, headers=headers).json()
        for o in (0, 3, 6)
    ]

    ids = [e["id"] for page in pages for e in page["items"]]
    assert [len(p["items"]) for p in pages] == [3, 3, 1]
    assert len(set(ids)) == 7  # no duplicates, nothing skipped, despite equal sort keys
    assert pages[0]["total"] == 7
    assert client.get(url(org), params={"limit": 101}, headers=headers).status_code == 422


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("hopper", {"Grace"}),
        ("grace hop", {"Grace"}),  # full name
        ("@globex-mail", {"Alan"}),  # email
        ("e-77", {"Ada"}),  # employee number, case-insensitive
        ("100%", {"Linus"}),  # LIKE wildcard matched literally
        ("_", set()),  # "_" is not a single-character wildcard
    ],
)
def test_search(client: TestClient, db_session: Session, term: str, expected: set[str]) -> None:
    org = create_organization(db_session)
    create_employee(db_session, org, first_name="Grace", last_name="Hopper")
    create_employee(
        db_session, org, first_name="Alan", last_name="Turing", email="alan@globex-mail.example"
    )
    create_employee(db_session, org, first_name="Ada", last_name="Lovelace", employee_number="E-77")
    create_employee(db_session, org, first_name="Linus", last_name="100%")

    body = client.get(url(org), params={"search": term}, headers=member(db_session, org)).json()

    assert {e["first_name"] for e in body["items"]} == expected


def test_filters(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    eng = create_department(db_session, org, "Engineering")
    boss = create_employee(db_session, org, first_name="Boss", department=eng)
    create_employee(
        db_session,
        org,
        first_name="Rae",
        department=eng,
        manager=boss,
        location="Pune",
        joining_date=date(2025, 3, 1),
    )
    create_employee(
        db_session,
        org,
        first_name="Lee",
        employment_status=EmploymentStatus.ON_LEAVE,
        location="pune",
        joining_date=date(2023, 6, 1),
    )
    headers = member(db_session, org, VIEWER)

    def names(**params: str) -> set[str]:
        response = client.get(url(org), params=params, headers=headers)
        assert response.status_code == 200, response.text
        return {e["first_name"] for e in response.json()["items"]}

    assert names(department_id=str(eng.id)) == {"Boss", "Rae"}
    assert names(manager_id=str(boss.id)) == {"Rae"}
    assert names(employment_status="on_leave") == {"Lee"}
    assert names(location="PUNE") == {"Rae", "Lee"}
    assert names(joined_from="2025-01-01") == {"Rae"}
    assert names(joined_to="2023-12-31") == {"Lee"}
    assert names(department_id=str(eng.id), location="pune") == {"Rae"}

    bad = client.get(
        url(org), params={"joined_from": "2025-02-01", "joined_to": "2025-01-01"}, headers=headers
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "invalid_date_range"
    assert (
        client.get(url(org), params={"employment_status": "x"}, headers=headers).status_code == 422
    )


def test_sorting(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    create_employee(db_session, org, last_name="Baker", joining_date=date(2022, 1, 1))
    create_employee(db_session, org, last_name="Adams", joining_date=date(2024, 1, 1))
    create_employee(db_session, org, last_name="Clark", joining_date=date(2023, 1, 1))
    headers = member(db_session, org, VIEWER)

    def order(sort: str) -> list[str]:
        items = client.get(url(org), params={"sort": sort}, headers=headers).json()["items"]
        return [e["last_name"] for e in items]

    assert order("last_name") == ["Adams", "Baker", "Clark"]
    assert order("-last_name") == ["Clark", "Baker", "Adams"]
    assert order("-joining_date") == ["Adams", "Clark", "Baker"]
    assert client.get(url(org), params={"sort": "email"}, headers=headers).status_code == 422


def test_list_never_includes_other_organizations(client: TestClient, db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    create_employee(db_session, acme, first_name="Mine")
    create_employee(db_session, globex, first_name="Theirs")

    body = client.get(url(acme), headers=member(db_session, acme, VIEWER)).json()

    assert [e["first_name"] for e in body["items"]] == ["Mine"]
    assert body["total"] == 1


# ---- update --------------------------------------------------------------------------


def test_partial_update_changes_only_sent_fields(
    client: TestClient, db_session: Session, events: pytest.LogCaptureFixture
) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org, designation="Engineer", location="Bengaluru")

    response = client.patch(
        url(org, employee.id), json={"designation": "Lead"}, headers=member(db_session, org)
    )

    assert response.status_code == 200
    assert response.json()["designation"] == "Lead"
    assert response.json()["location"] == "Bengaluru"
    assert emitted(events) == [("employee.updated", str(employee.id), ["designation"])]


def test_one_update_can_emit_several_events(
    client: TestClient, db_session: Session, events: pytest.LogCaptureFixture
) -> None:
    org = create_organization(db_session)
    eng, sales = (
        create_department(db_session, org, "Eng"),
        create_department(db_session, org, "Sales"),
    )
    old_boss, new_boss = create_employee(db_session, org), create_employee(db_session, org)
    employee = create_employee(db_session, org, department=eng, manager=old_boss)

    response = client.patch(
        url(org, employee.id),
        json={"department_id": str(sales.id), "manager_id": str(new_boss.id), "location": "Pune"},
        headers=member(db_session, org),
    )

    assert response.status_code == 200
    assert response.json()["department"]["name"] == "Sales"  # response reflects the change
    assert response.json()["manager"]["id"] == str(new_boss.id)
    assert [e[0] for e in emitted(events)] == [
        "employee.department_changed",
        "employee.manager_changed",
        "employee.updated",
    ]


def test_update_that_changes_nothing_emits_no_event(
    client: TestClient, db_session: Session, events: pytest.LogCaptureFixture
) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org, location="Pune")

    response = client.patch(
        url(org, employee.id), json={"location": "Pune"}, headers=member(db_session, org)
    )

    assert response.status_code == 200
    assert emitted(events) == []


def test_optional_fields_can_be_cleared_with_null(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    dept = create_department(db_session, org, "Ops")
    boss = create_employee(db_session, org)
    employee = create_employee(db_session, org, department=dept, manager=boss)

    body = client.patch(
        url(org, employee.id),
        json={"department_id": None, "manager_id": None, "location": None},
        headers=member(db_session, org),
    ).json()

    assert body["department"] is None and body["manager"] is None and body["location"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"email": None},
        {"joining_date": None},
        {"employment_status": "terminated"},  # must use /terminate
        {"unknown_field": "x"},
        {"organization_id": str(uuid.uuid4())},  # cannot move an employee between tenants
    ],
)
def test_update_rejects_invalid_input(
    client: TestClient, db_session: Session, body: dict[str, Any]
) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)

    response = client.patch(url(org, employee.id), json=body, headers=member(db_session, org))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_update_rejects_duplicate_email(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    create_employee(db_session, org, email="taken@acme.example")
    employee = create_employee(db_session, org)

    response = client.patch(
        url(org, employee.id), json={"email": "TAKEN@acme.example"}, headers=member(db_session, org)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_keeping_own_email_is_not_a_duplicate(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org, email="me@acme.example")

    response = client.patch(
        url(org, employee.id), json={"email": "me@acme.example"}, headers=member(db_session, org)
    )

    assert response.status_code == 200


def test_manager_cycles_are_rejected(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    ceo = create_employee(db_session, org, first_name="Ceo")
    vp = create_employee(db_session, org, first_name="Vp", manager=ceo)
    engineer = create_employee(db_session, org, first_name="Eng", manager=vp)
    headers = member(db_session, org)

    for employee, new_manager in [(ceo, engineer), (ceo, vp), (vp, vp)]:
        response = client.patch(
            url(org, employee.id), json={"manager_id": str(new_manager.id)}, headers=headers
        )
        assert response.status_code == 422, (employee.first_name, new_manager.first_name)
        assert response.json()["error"]["code"] == "manager_cycle"

    # Moving sideways is fine: the engineer reports straight to the CEO.
    ok = client.patch(url(org, engineer.id), json={"manager_id": str(ceo.id)}, headers=headers)
    assert ok.status_code == 200


def test_status_can_move_between_active_and_on_leave(
    client: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)
    headers = member(db_session, org)

    leave = client.patch(
        url(org, employee.id), json={"employment_status": "on_leave"}, headers=headers
    )
    back = client.patch(
        url(org, employee.id), json={"employment_status": "active"}, headers=headers
    )

    assert leave.json()["employment_status"] == "on_leave"
    assert back.json()["employment_status"] == "active"


def test_terminated_employee_cannot_be_modified(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    employee = create_employee(
        db_session,
        org,
        employment_status=EmploymentStatus.TERMINATED,
        termination_date=date(2025, 1, 31),
    )

    response = client.patch(
        url(org, employee.id), json={"location": "Pune"}, headers=member(db_session, org)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "employee_terminated"


# ---- terminate -----------------------------------------------------------------------


def test_terminate_reassigns_direct_reports(
    client: TestClient, db_session: Session, events: pytest.LogCaptureFixture
) -> None:
    org = create_organization(db_session)
    director = create_employee(db_session, org, first_name="Dir")
    lead = create_employee(db_session, org, first_name="Lead", manager=director)
    report_a = create_employee(db_session, org, first_name="A", manager=lead)
    report_b = create_employee(db_session, org, first_name="B", manager=lead)
    headers = member(db_session, org)

    response = client.post(
        url(org, lead.id, "terminate"), json={"termination_date": "2026-03-31"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["employment_status"] == "terminated"
    assert response.json()["termination_date"] == "2026-03-31"
    for report in (report_a, report_b):
        moved = client.get(url(org, report.id), headers=headers).json()
        assert moved["manager"]["id"] == str(director.id)
    assert emitted(events) == [
        ("employee.terminated", str(lead.id), ["employment_status", "termination_date"]),
        *sorted(
            [
                ("employee.manager_changed", str(report_a.id), ["manager_id"]),
                ("employee.manager_changed", str(report_b.id), ["manager_id"]),
            ],
            key=lambda e: e[1],
        ),
    ]


def test_terminating_a_top_level_manager_leaves_reports_without_manager(
    client: TestClient, db_session: Session
) -> None:
    org = create_organization(db_session)
    ceo = create_employee(db_session, org)
    report = create_employee(db_session, org, manager=ceo)
    headers = member(db_session, org)

    client.post(url(org, ceo.id, "terminate"), headers=headers)

    assert client.get(url(org, report.id), headers=headers).json()["manager"] is None


def test_terminate_defaults_to_today_and_is_final(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)
    headers = member(db_session, org)

    first = client.post(url(org, employee.id, "terminate"), headers=headers)
    second = client.post(url(org, employee.id, "terminate"), headers=headers)

    assert first.status_code == 200
    assert first.json()["termination_date"] == datetime.now(UTC).date().isoformat()
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "employee_terminated"


def test_termination_cannot_precede_joining(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org, joining_date=date(2025, 6, 1))

    response = client.post(
        url(org, employee.id, "terminate"),
        json={"termination_date": "2025-05-31"},
        headers=member(db_session, org),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "termination_before_joining"


# ---- archive -------------------------------------------------------------------------


def test_archive_lifecycle(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)
    headers = member(db_session, org)

    not_yet = client.delete(url(org, employee.id), headers=headers)
    assert not_yet.status_code == 409
    assert not_yet.json()["error"]["code"] == "employee_not_terminated"

    client.post(url(org, employee.id, "terminate"), headers=headers)
    assert client.delete(url(org, employee.id), headers=headers).status_code == 204
    assert client.delete(url(org, employee.id), headers=headers).status_code == 204  # idempotent

    assert client.get(url(org), headers=headers).json()["total"] == 0
    archived = client.get(url(org), params={"include_archived": "true"}, headers=headers).json()
    assert [e["id"] for e in archived["items"]] == [str(employee.id)]
    still_readable = client.get(url(org, employee.id), headers=headers).json()
    assert still_readable["archived_at"] is not None


# ---- authorization and isolation -----------------------------------------------------


@pytest.mark.parametrize("role", [MANAGER, VIEWER])
def test_read_only_roles_cannot_write(
    client: TestClient, db_session: Session, role: OrganizationRole
) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)
    headers = member(db_session, org, role)

    assert client.get(url(org), headers=headers).status_code == 200
    assert client.get(url(org, employee.id), headers=headers).status_code == 200
    for response in (
        client.post(url(org), json=new_employee(), headers=headers),
        client.patch(url(org, employee.id), json={"location": "X"}, headers=headers),
        client.post(url(org, employee.id, "terminate"), headers=headers),
        client.delete(url(org, employee.id), headers=headers),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["details"]["required_permission"] == "employees:write"


def test_cross_organization_access_is_404_everywhere(
    client: TestClient, db_session: Session
) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    victim = create_employee(db_session, globex)
    acme_admin = member(db_session, acme)

    # 1) Globex's employee through Acme's URL: unknown employee.
    for response in (
        client.get(url(acme, victim.id), headers=acme_admin),
        client.patch(url(acme, victim.id), json={"location": "X"}, headers=acme_admin),
        client.post(url(acme, victim.id, "terminate"), headers=acme_admin),
        client.delete(url(acme, victim.id), headers=acme_admin),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "employee_not_found"

    # 2) Globex's URL: the organization itself is hidden.
    for response in (
        client.get(url(globex), headers=acme_admin),
        client.get(url(globex, victim.id), headers=acme_admin),
        client.post(url(globex), json=new_employee(), headers=acme_admin),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "organization_not_found"

    # The victim is untouched.
    db_session.refresh(victim)
    assert victim.employment_status is EmploymentStatus.ACTIVE


def test_superadmin_can_manage_any_organization(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)
    root = auth_headers(create_user(db_session, is_superadmin=True))

    response = client.post(url(org), json=new_employee(), headers=root)

    assert response.status_code == 201


def test_requires_authentication(client: TestClient, db_session: Session) -> None:
    org = create_organization(db_session)

    assert client.get(url(org)).status_code == 401
    assert client.post(url(org), json=new_employee()).status_code == 401
