"""API v2: cursor-paginated employee list, and v1 left unchanged."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Employee, EmploymentStatus, Organization, OrganizationRole, User
from tests.factories import (
    add_member,
    auth_headers,
    create_employee,
    create_organization,
    create_user,
)

NAMES = [
    "Adams", "Baker", "Clark", "Davis", "Evans", "Fisher", "Garcia", "Hughes", "Iyer",
    "Jones", "Khan", "Lopez", "Mehta", "Nair", "Ortiz", "Patel", "Quinn", "Rao", "Shah",
    "Turner", "Usman", "Verma", "Walsh", "Xu", "Young",
]  # fmt: skip


@pytest.fixture
def org(db_session: Session) -> Organization:
    organization = create_organization(db_session)
    for i, last in enumerate(NAMES):
        create_employee(
            db_session,
            organization,
            first_name="Sam",
            last_name=last,
            joining_date=date(2024, 1, 1) + timedelta(days=(i * 7) % 60),  # repeats dates
        )
    # Same name twice: the ID breaks the tie, so the order is still total.
    create_employee(db_session, organization, first_name="Sam", last_name="Patel")
    return organization


@pytest.fixture
def reader(db_session: Session, org: Organization) -> User:
    user = create_user(db_session)
    add_member(db_session, user, org, OrganizationRole.VIEWER)
    return user


def _url(org: Organization, version: str = "v2") -> str:
    return f"/api/{version}/organizations/{org.id}/employees"


def _walk(client: TestClient, org: Organization, user: User, **params: object) -> list[list[dict]]:
    pages, cursor = [], None
    while True:
        query = {**params, **({"cursor": cursor} if cursor else {})}
        response = client.get(_url(org), params=query, headers=auth_headers(user))
        assert response.status_code == 200, response.text
        body = response.json()
        pages.append(body["data"])
        if not body["page"]["has_more"]:
            assert body["page"]["next_cursor"] is None
            return pages
        cursor = body["page"]["next_cursor"]


def test_pages_cover_every_employee_once_in_the_v1_order(
    client: TestClient, org: Organization, reader: User
) -> None:
    pages = _walk(client, org, reader, limit=10)
    assert [len(p) for p in pages] == [10, 10, 6]
    ids = [e["id"] for page in pages for e in page]
    assert len(ids) == len(set(ids)) == 26

    v1 = client.get(_url(org, "v1"), params={"limit": 100}, headers=auth_headers(reader)).json()
    assert ids == [e["id"] for e in v1["items"]]  # same sort: last name, first name, id


def test_response_shape_has_no_total_or_offset(
    client: TestClient, org: Organization, reader: User
) -> None:
    body = client.get(_url(org), params={"limit": 2}, headers=auth_headers(reader)).json()
    assert set(body) == {"data", "page"}
    assert set(body["page"]) == {"limit", "next_cursor", "has_more"}
    assert body["page"]["limit"] == 2 and body["page"]["has_more"] is True
    # Items are the same employee representation as in v1.
    v1_item = client.get(_url(org, "v1"), params={"limit": 1}, headers=auth_headers(reader))
    assert set(body["data"][0]) == set(v1_item.json()["items"][0])


@pytest.mark.parametrize(
    ("sort", "key"),
    [
        ("joining_date", lambda e: (e["joining_date"], e["id"])),
        ("-created_at", lambda e: (e["created_at"], e["id"])),
    ],
)
def test_other_sorts_page_in_a_total_order(
    client: TestClient, org: Organization, reader: User, sort: str, key
) -> None:
    rows = [e for page in _walk(client, org, reader, limit=7, sort=sort) for e in page]
    assert len({e["id"] for e in rows}) == 26
    expected = sorted(rows, key=key, reverse=sort.startswith("-"))
    assert [e["id"] for e in rows] == [e["id"] for e in expected]


def test_inserts_and_removals_before_the_position_do_not_shift_later_pages(
    client: TestClient, db_session: Session, org: Organization, reader: User
) -> None:
    headers = auth_headers(reader)
    first = client.get(_url(org), params={"limit": 5}, headers=headers).json()
    seen = [e["id"] for e in first["data"]]  # Adams .. Evans

    # While the client is between pages: two people are hired who sort first, and someone
    # already seen is archived (net one row more before the position). With OFFSET the
    # next page would repeat "Evans"; with the cursor it continues exactly after it.
    create_employee(db_session, org, first_name="Sam", last_name="Aaronson")
    create_employee(db_session, org, first_name="Sam", last_name="Abbott")
    adams = db_session.get(Employee, seen[0])
    assert adams is not None
    adams.archived_at = adams.updated_at
    db_session.flush()

    second = client.get(
        _url(org), params={"limit": 5, "cursor": first["page"]["next_cursor"]}, headers=headers
    ).json()
    assert [e["last_name"] for e in second["data"]] == [
        "Fisher",
        "Garcia",
        "Hughes",
        "Iyer",
        "Jones",
    ]

    # The same moment with v1 offsets: page 2 starts one row too early and repeats Evans.
    v1_second = client.get(
        _url(org, "v1"), params={"limit": 5, "offset": 5}, headers=headers
    ).json()
    assert v1_second["items"][0]["id"] == seen[-1]


def test_filters_apply_and_a_cursor_only_works_with_its_own_query(
    client: TestClient, db_session: Session, org: Organization, reader: User
) -> None:
    create_employee(db_session, org, last_name="Zed", employment_status=EmploymentStatus.ON_LEAVE)
    headers = auth_headers(reader)
    on_leave = client.get(
        _url(org), params={"employment_status": "on_leave"}, headers=headers
    ).json()
    assert [e["last_name"] for e in on_leave["data"]] == ["Zed"]

    page = client.get(_url(org), params={"limit": 3}, headers=headers).json()
    cursor = page["page"]["next_cursor"]
    for other in ({"search": "sam"}, {"sort": "joining_date"}, {"include_archived": "true"}):
        refused = client.get(
            _url(org), params={"limit": 3, "cursor": cursor, **other}, headers=headers
        )
        assert refused.status_code == 422, other
        assert refused.json()["error"]["code"] == "invalid_cursor"


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!",
        "eyJzIjoibGFzdF9uYW1lIn0",  # valid base64 JSON without the key
    ],
)
def test_malformed_cursors_are_refused(
    client: TestClient, org: Organization, reader: User, cursor: str
) -> None:
    response = client.get(_url(org), params={"cursor": cursor}, headers=auth_headers(reader))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_a_cursor_with_a_wrong_key_is_refused(
    client: TestClient, org: Organization, reader: User
) -> None:
    import base64
    import json

    page = client.get(_url(org), params={"limit": 2}, headers=auth_headers(reader)).json()
    padded = page["page"]["next_cursor"] + "=" * (-len(page["page"]["next_cursor"]) % 4)
    data = json.loads(base64.urlsafe_b64decode(padded))
    data["k"] = ["Baker", "Sam", "not-a-uuid"]
    forged = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    response = client.get(
        _url(org), params={"limit": 2, "cursor": forged}, headers=auth_headers(reader)
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_cursor"


def test_organization_isolation_and_cursor_scope(
    client: TestClient, db_session: Session, org: Organization, reader: User
) -> None:
    outsider = create_user(db_session)
    assert client.get(_url(org), headers=auth_headers(outsider)).status_code == 404
    assert client.get(_url(org)).status_code == 401

    # A cursor from one organization is refused in another, even for a member of both.
    other = create_organization(db_session)
    add_member(db_session, reader, other, OrganizationRole.VIEWER)
    for last in ("Adams", "Baker", "Clark"):
        create_employee(db_session, other, last_name=last)
    cursor = client.get(_url(org), params={"limit": 1}, headers=auth_headers(reader)).json()[
        "page"
    ]["next_cursor"]
    refused = client.get(
        _url(other), params={"limit": 1, "cursor": cursor}, headers=auth_headers(reader)
    )
    assert refused.status_code == 422


def test_limit_is_bounded(client: TestClient, org: Organization, reader: User) -> None:
    assert (
        client.get(_url(org), params={"limit": 101}, headers=auth_headers(reader)).status_code
        == 422
    )
    assert (
        client.get(_url(org), params={"limit": 0}, headers=auth_headers(reader)).status_code == 422
    )


def test_v1_is_unchanged(client: TestClient, org: Organization, reader: User) -> None:
    body = client.get(
        _url(org, "v1"), params={"limit": 5, "offset": 5}, headers=auth_headers(reader)
    ).json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["total"] == 26 and body["offset"] == 5 and len(body["items"]) == 5
