"""Data integrity: field comparison, source-of-truth policies, conflict detection and
resolution, against the mock applications."""

import json
import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.connectors.base import ExternalUser
from app.core.config import Settings
from app.core.errors import ConflictError, PermissionDeniedError, UnprocessableError
from app.integrity.fields import (
    DEFAULT_POLICIES,
    EffectivePolicy,
    differences,
    external_values,
    severity_for,
)
from app.models import (
    CONFLICT_FIELDS,
    AuditLog,
    ConflictSeverity,
    ConflictStatus,
    Connector,
    DataConflict,
    Department,
    Employee,
    ExternalAccount,
    ExternalAccountStatus,
    IntegrationEvent,
    Organization,
    OrganizationRole,
    PolicySource,
    ResolutionKind,
    ResolutionMode,
    StepOperation,
    User,
)
from app.schemas.employees import EmployeeCreate
from app.schemas.workflows import StepInput
from app.services.conflicts import ConflictService
from app.services.connectors import ConnectorService
from app.services.employees import EmployeeService
from app.services.workflows import WorkflowService
from app.workflows.engine import EventProcessor
from tests.factories import (
    add_member,
    auth_headers,
    create_department,
    create_organization,
    create_user,
)
from tests.mock_servers import MOCK_CREDENTIALS, RunningMock

TYPES = ("slack", "google_workspace", "payroll")

# ---- comparison (pure) -------------------------------------------------------------------


def user(**overrides: object) -> ExternalUser:
    values = {
        "external_id": "X1",
        "email": "grace@acme.example",
        "first_name": "Grace",
        "last_name": "Hopper",
        "active": True,
        "department": "Engineering",
        "designation": "Engineer",
        "location": None,
    }
    values.update(overrides)
    return ExternalUser(**values)  # type: ignore[arg-type]


OURS = {
    "first_name": "Grace",
    "last_name": "Hopper",
    "email": "grace@acme.example",
    "department": "Engineering",
    "designation": "Engineer",
    "location": "Pune",
    "account_active": "true",
}


def test_equal_records_have_no_differences_and_unreported_fields_are_skipped() -> None:
    # location: the application does not report it -> not a conflict
    assert differences(OURS, external_values(user())) == {}


def test_case_and_spaces_do_not_count_for_email_department_designation() -> None:
    theirs = external_values(
        user(email="GRACE@acme.example", department=" engineering", designation="ENGINEER")
    )

    assert differences(OURS, theirs) == {}


def test_real_differences_are_found() -> None:
    theirs = external_values(user(department="Finance", active=False, first_name="Gracie"))

    assert differences(OURS, theirs) == {
        "first_name": ("Grace", "Gracie"),
        "department": ("Engineering", "Finance"),
        "account_active": ("true", "false"),
    }


def test_a_terminated_person_with_an_active_account_is_critical() -> None:
    policy = EffectivePolicy(
        "account_active",
        PolicySource.SYNCFORGE,
        None,
        ResolutionMode.MANUAL,
        ConflictSeverity.HIGH,
        False,
    )

    assert severity_for("account_active", policy, "false", "true") is ConflictSeverity.CRITICAL
    assert severity_for("account_active", policy, "true", "false") is ConflictSeverity.HIGH


def test_every_field_has_a_default_policy_and_hr_is_the_default_authority() -> None:
    assert set(DEFAULT_POLICIES) == set(CONFLICT_FIELDS)
    assert {source for source, _, _ in DEFAULT_POLICIES.values()} == {PolicySource.SYNCFORGE}


# ---- the scenario: one hire, synchronized to three applications --------------------------


@dataclass
class World:
    org: Organization
    admin: User
    employee: Employee
    apps: dict[str, Connector]
    engineering: Department
    external_ids: dict[str, str]


@pytest.fixture
def world(
    db_session: Session, mocks: dict[str, RunningMock], connector_settings: Settings
) -> World:
    org = create_organization(db_session)
    admin = create_user(db_session)
    add_member(db_session, admin, org, OrganizationRole.ORG_ADMIN)
    engineering = create_department(db_session, org, "Engineering")
    create_department(db_session, org, "Finance")
    service = ConnectorService(db_session, connector_settings)
    apps = {
        t: service.create(org, connector_type=t, name=t, config={}, credentials=MOCK_CREDENTIALS[t])
        for t in TYPES
    }
    workflows = WorkflowService(db_session)
    workflow = workflows.create(
        org,
        name="Onboarding",
        description=None,
        trigger_event_type="employee.created",
        steps=[
            StepInput(connector_id=apps[t].id, operation=StepOperation.CREATE_USER) for t in TYPES
        ],
    )
    workflows.set_active(org, workflow.id, active=True)
    employees = EmployeeService(db_session)
    employee = employees.create(
        org,
        EmployeeCreate(
            employee_number="E-100",
            first_name="Grace",
            last_name="Hopper",
            email="grace.hopper@acme.example",
            department_id=engineering.id,
            designation="Engineer",
            location="Pune",
            joining_date="2026-11-01",
        ),
    )
    EventProcessor(db_session, connector_settings).process(employees.recorded_events[0].id)
    external_ids = {
        t: db_session.scalar(
            select(ExternalAccount.external_id).where(
                ExternalAccount.connector_id == apps[t].id,
                ExternalAccount.employee_id == employee.id,
            )
        )
        for t in TYPES
    }
    assert all(external_ids.values())
    audit.set_actor(db_session, admin.id)  # what follows is done by the admin
    return World(org, admin, employee, apps, engineering, external_ids)


def google_user(mocks: dict[str, RunningMock], world: World) -> dict:
    return mocks["google_workspace"].state.users[world.external_ids["google_workspace"]]


def move_in_google(mocks: dict[str, RunningMock], world: World, department: str) -> None:
    """Someone changes the department directly in the Google Admin console."""
    google_user(mocks, world)["organizations"][0]["department"] = department


def open_conflicts(session: Session, world: World) -> list[DataConflict]:
    return list(
        session.scalars(
            select(DataConflict).where(
                DataConflict.organization_id == world.org.id,
                DataConflict.status == ConflictStatus.OPEN,
            )
        )
    )


def service(session: Session, settings: Settings) -> ConflictService:
    return ConflictService(session, settings)


def resolve(
    session: Session,
    settings: Settings,
    world: World,
    conflict: DataConflict,
    resolution: ResolutionKind,
    **kwargs: object,
) -> DataConflict:
    params = {"note": None, "override": False, "can_write_employees": True, **kwargs}
    return service(session, settings).resolve(
        world.org, conflict.id, resolution=resolution, actor=world.admin, **params
    )


def test_matching_records_produce_no_conflict(
    db_session: Session, world: World, connector_settings: Settings
) -> None:
    for app in TYPES:
        result = service(db_session, connector_settings).reconcile(world.org, world.apps[app].id)
        assert (result.accounts_checked, result.conflicts_opened, result.errors) == (1, 0, [])


def test_a_difference_is_recorded_not_overwritten(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    move_in_google(mocks, world, "Finance")

    result = service(db_session, connector_settings).reconcile(
        world.org, world.apps["google_workspace"].id
    )

    assert result.conflicts_opened == 1
    [conflict] = open_conflicts(db_session, world)
    assert (conflict.field, conflict.syncforge_value, conflict.external_value) == (
        "department",
        "Engineering",
        "Finance",
    )
    assert (conflict.authoritative_source, conflict.severity) == (
        PolicySource.SYNCFORGE,
        ConflictSeverity.MEDIUM,
    )
    db_session.refresh(world.employee)
    assert world.employee.department_id == world.engineering.id  # SyncForge untouched
    assert google_user(mocks, world)["organizations"][0]["department"] == "Finance"  # and Google
    detected = db_session.scalar(select(AuditLog).where(AuditLog.action == "conflict.detected"))
    assert detected.details["field"] == "department"
    assert detected.details["external_value"] == "Finance"  # not personal: recorded


def test_a_repeated_detection_refreshes_the_same_conflict(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    move_in_google(mocks, world, "Finance")
    conflicts = service(db_session, connector_settings)
    conflicts.reconcile(world.org, world.apps["google_workspace"].id)

    again = conflicts.reconcile(world.org, world.apps["google_workspace"].id)

    assert (again.conflicts_opened, again.conflicts_refreshed) == (0, 1)
    [conflict] = open_conflicts(db_session, world)
    assert conflict.times_detected == 2


def test_a_conflict_fixed_elsewhere_closes_itself(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    move_in_google(mocks, world, "Finance")
    conflicts = service(db_session, connector_settings)
    conflicts.reconcile(world.org, world.apps["google_workspace"].id)
    move_in_google(mocks, world, "Engineering")  # someone put it back

    result = conflicts.reconcile(world.org, world.apps["google_workspace"].id)

    assert result.conflicts_closed == 1
    assert open_conflicts(db_session, world) == []
    conflict = db_session.scalar(select(DataConflict))
    [history] = conflicts.resolutions(conflict)
    assert (history.resolution, history.automatic) == (ResolutionKind.NO_LONGER_DIFFERENT, True)


def test_hr_wins_pushes_syncforges_value_to_the_application(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    move_in_google(mocks, world, "Finance")
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)

    resolved = resolve(
        db_session, connector_settings, world, conflict, ResolutionKind.USE_SYNCFORGE
    )

    assert resolved.status is ConflictStatus.RESOLVED
    assert google_user(mocks, world)["organizations"][0]["department"] == "Engineering"
    [history] = service(db_session, connector_settings).resolutions(resolved)
    assert (history.resolution, history.resolved_by_user_id, history.applied_value) == (
        ResolutionKind.USE_SYNCFORGE,
        world.admin.id,
        "Engineering",
    )
    entry = db_session.scalar(select(AuditLog).where(AuditLog.action == "conflict.resolved"))
    assert entry.actor_user_id == world.admin.id


def make_google_authoritative_for_department(
    session: Session, settings: Settings, world: World, mode: ResolutionMode = ResolutionMode.MANUAL
) -> None:
    service(session, settings).set_policy(
        world.org,
        "department",
        source=PolicySource.CONNECTOR,
        connector_id=world.apps["google_workspace"].id,
        resolution_mode=mode,
        severity=ConflictSeverity.HIGH,
    )


def test_when_the_application_is_authoritative_its_value_is_adopted(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    make_google_authoritative_for_department(db_session, connector_settings, world)
    move_in_google(mocks, world, "Finance")
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)
    assert (conflict.authoritative_source, conflict.severity) == (
        PolicySource.CONNECTOR,
        ConflictSeverity.HIGH,
    )
    events_before = db_session.scalar(select(func.count()).select_from(IntegrationEvent))

    resolve(db_session, connector_settings, world, conflict, ResolutionKind.USE_EXTERNAL)

    db_session.refresh(world.employee)
    assert world.employee.department.name == "Finance"
    assert world.employee.version == 2  # an ordinary, versioned update...
    new_events = db_session.scalars(
        select(IntegrationEvent.event_type).order_by(IntegrationEvent.created_at.desc())
    ).all()
    assert db_session.scalar(select(func.count()).select_from(IntegrationEvent)) == (
        events_before + 1
    )
    assert "employee.department_changed" in new_events  # ...that propagates to other apps


def test_deciding_against_the_policy_needs_override_and_a_note(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    move_in_google(mocks, world, "Finance")  # default policy: HR is authoritative
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)

    with pytest.raises(UnprocessableError) as refused:
        resolve(db_session, connector_settings, world, conflict, ResolutionKind.USE_EXTERNAL)
    with pytest.raises(UnprocessableError) as no_note:
        resolve(
            db_session,
            connector_settings,
            world,
            conflict,
            ResolutionKind.USE_EXTERNAL,
            override=True,
        )
    accepted = resolve(
        db_session,
        connector_settings,
        world,
        conflict,
        ResolutionKind.USE_EXTERNAL,
        override=True,
        note="HR record was wrong; confirmed with the manager.",
    )

    assert refused.value.code == "resolution_against_policy"
    assert no_note.value.code == "note_required"
    [history] = service(db_session, connector_settings).resolutions(accepted)
    assert history.against_policy is True
    db_session.refresh(world.employee)
    assert world.employee.department.name == "Finance"


def test_adopting_into_the_employee_record_needs_employees_write(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    make_google_authoritative_for_department(db_session, connector_settings, world)
    move_in_google(mocks, world, "Finance")
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)

    with pytest.raises(PermissionDeniedError):
        resolve(
            db_session,
            connector_settings,
            world,
            conflict,
            ResolutionKind.USE_EXTERNAL,
            can_write_employees=False,
        )


def test_an_unknown_department_is_not_invented(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    make_google_authoritative_for_department(db_session, connector_settings, world)
    move_in_google(mocks, world, "Marketing")  # does not exist in SyncForge
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)

    with pytest.raises(UnprocessableError) as raised:
        resolve(db_session, connector_settings, world, conflict, ResolutionKind.USE_EXTERNAL)

    assert raised.value.code == "department_not_found"
    assert [c.id for c in open_conflicts(db_session, world)] == [conflict.id]  # still open


def test_a_decision_on_outdated_values_is_refused(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    move_in_google(mocks, world, "Marketing")
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)
    finance = db_session.scalar(select(Department).where(Department.name == "Finance"))
    EmployeeService(db_session).update(world.org, world.employee.id, {"department_id": finance.id})

    with pytest.raises(ConflictError) as raised:
        resolve(db_session, connector_settings, world, conflict, ResolutionKind.USE_SYNCFORGE)

    assert raised.value.code == "conflict_stale"


def test_adopting_refuses_if_the_employee_changed_since_detection(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    make_google_authoritative_for_department(db_session, connector_settings, world)
    move_in_google(mocks, world, "Finance")
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)
    EmployeeService(db_session).update(world.org, world.employee.id, {"location": "Goa"})

    with pytest.raises(ConflictError) as raised:
        resolve(db_session, connector_settings, world, conflict, ResolutionKind.USE_EXTERNAL)

    assert raised.value.code == "conflict_stale"
    db_session.refresh(world.employee)
    assert world.employee.department.name == "Engineering"


def test_dismissing_needs_a_note_and_a_closed_conflict_stays_closed(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    move_in_google(mocks, world, "Finance")
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)

    with pytest.raises(UnprocessableError) as no_note:
        resolve(db_session, connector_settings, world, conflict, ResolutionKind.DISMISS)
    dismissed = resolve(
        db_session,
        connector_settings,
        world,
        conflict,
        ResolutionKind.DISMISS,
        note="Shared mailbox owner; expected to differ.",
    )
    with pytest.raises(ConflictError) as again:
        resolve(db_session, connector_settings, world, conflict, ResolutionKind.USE_SYNCFORGE)

    assert no_note.value.code == "note_required"
    assert dismissed.status is ConflictStatus.DISMISSED
    assert again.value.code == "conflict_not_open"
    assert google_user(mocks, world)["organizations"][0]["department"] == "Finance"  # untouched


def test_auto_mode_applies_the_authoritative_value_at_once(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    service(db_session, connector_settings).set_policy(
        world.org,
        "department",
        source=PolicySource.SYNCFORGE,
        connector_id=None,
        resolution_mode=ResolutionMode.AUTO,
        severity=ConflictSeverity.MEDIUM,
    )
    move_in_google(mocks, world, "Finance")

    result = service(db_session, connector_settings).reconcile(
        world.org, world.apps["google_workspace"].id
    )

    assert (result.conflicts_opened, result.auto_resolved) == (1, 1)
    assert open_conflicts(db_session, world) == []
    assert google_user(mocks, world)["organizations"][0]["department"] == "Engineering"
    conflict = db_session.scalar(select(DataConflict))
    [history] = service(db_session, connector_settings).resolutions(conflict)
    assert (history.automatic, history.resolved_by_user_id) == (True, None)


def test_a_terminated_person_still_active_in_slack_is_critical_and_can_be_deactivated(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    # Terminated in HR, but there is no offboarding workflow: Slack still has the account.
    EmployeeService(db_session).terminate(world.org, world.employee.id, termination_date=None)
    service(db_session, connector_settings).reconcile(world.org, world.apps["slack"].id)
    [conflict] = open_conflicts(db_session, world)
    assert (conflict.field, conflict.severity) == ("account_active", ConflictSeverity.CRITICAL)

    resolve(db_session, connector_settings, world, conflict, ResolutionKind.USE_SYNCFORGE)

    assert mocks["slack"].state.users[world.external_ids["slack"]]["active"] is False


def test_an_identity_provider_can_be_authoritative_for_account_status(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    service(db_session, connector_settings).set_policy(
        world.org,
        "account_active",
        source=PolicySource.CONNECTOR,
        connector_id=world.apps["google_workspace"].id,
        resolution_mode=ResolutionMode.MANUAL,
        severity=ConflictSeverity.HIGH,
    )
    google_user(mocks, world)["suspended"] = True  # security team suspended the account
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)
    assert conflict.authoritative_source is PolicySource.CONNECTOR

    resolve(
        db_session,
        connector_settings,
        world,
        conflict,
        ResolutionKind.USE_EXTERNAL,
        can_write_employees=False,  # account state only: no employee change needed
    )

    account = db_session.scalar(
        select(ExternalAccount).where(
            ExternalAccount.connector_id == world.apps["google_workspace"].id
        )
    )
    assert account.status is ExternalAccountStatus.DEACTIVATED
    db_session.refresh(world.employee)
    assert world.employee.version == 1  # the employee record itself is unchanged


def test_personal_values_never_reach_the_audit_log(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    google_user(mocks, world)["name"]["givenName"] = "Gracie"
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)
    resolve(db_session, connector_settings, world, conflict, ResolutionKind.USE_SYNCFORGE)

    entries = db_session.scalars(
        select(AuditLog.details).where(AuditLog.action.startswith("conflict."))
    ).all()
    assert len(entries) == 2
    assert "grace" not in json.dumps(entries).lower()


def test_an_account_deleted_in_the_application_is_reported(
    db_session: Session, world: World, mocks: dict[str, RunningMock], connector_settings: Settings
) -> None:
    del mocks["payroll"].state.users[world.external_ids["payroll"]]

    result = service(db_session, connector_settings).reconcile(world.org, world.apps["payroll"].id)

    assert result.accounts_checked == 0
    assert result.errors == [
        {"employee_id": str(world.employee.id), "category": "not_found", "code": "http_404"}
    ]


# ---- API ---------------------------------------------------------------------------------


def base(world: World) -> str:
    return f"/api/v1/organizations/{world.org.id}"


def member(session: Session, world: World, role: OrganizationRole) -> dict[str, str]:
    person = create_user(session)
    add_member(session, person, world.org, role)
    return auth_headers(person)


def test_api_reconcile_list_detail_and_resolve(
    client: TestClient,
    db_session: Session,
    world: World,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.conflicts.get_settings", lambda: connector_settings)
    move_in_google(mocks, world, "Finance")
    admin = auth_headers(world.admin)
    viewer = member(db_session, world, OrganizationRole.VIEWER)
    google = world.apps["google_workspace"].id

    refused = client.post(f"{base(world)}/connectors/{google}/reconcile", headers=viewer)
    run = client.post(f"{base(world)}/connectors/{google}/reconcile", headers=admin)
    listed = client.get(
        f"{base(world)}/conflicts", params={"conflict_status": "open"}, headers=viewer
    )
    conflict_id = listed.json()["items"][0]["id"]
    viewer_resolve = client.post(
        f"{base(world)}/conflicts/{conflict_id}/resolve",
        headers=viewer,
        json={"resolution": "use_syncforge"},
    )
    resolved = client.post(
        f"{base(world)}/conflicts/{conflict_id}/resolve",
        headers=admin,
        json={"resolution": "use_syncforge"},
    )
    detail = client.get(f"{base(world)}/conflicts/{conflict_id}", headers=viewer)

    assert refused.status_code == 403
    assert (run.status_code, run.json()["conflicts_opened"]) == (200, 1)
    assert listed.json()["total"] == 1
    assert viewer_resolve.status_code == 403
    assert (resolved.status_code, resolved.json()["status"]) == (200, "resolved")
    assert detail.json()["resolutions"][0]["resolution"] == "use_syncforge"


def test_api_policies(client: TestClient, db_session: Session, world: World) -> None:
    admin = auth_headers(world.admin)
    manager = member(db_session, world, OrganizationRole.INTEGRATION_MANAGER)
    google = str(world.apps["google_workspace"].id)
    body = {
        "source": "connector",
        "connector_id": google,
        "resolution_mode": "auto",
        "severity": "high",
    }

    defaults = client.get(f"{base(world)}/data-source-policies", headers=manager).json()
    by_manager = client.put(
        f"{base(world)}/data-source-policies/account_active", headers=manager, json=body
    )
    by_admin = client.put(
        f"{base(world)}/data-source-policies/account_active", headers=admin, json=body
    )
    missing_connector = client.put(
        f"{base(world)}/data-source-policies/email",
        headers=admin,
        json={**body, "connector_id": None},
    )
    foreign = client.put(
        f"{base(world)}/data-source-policies/email",
        headers=admin,
        json={**body, "connector_id": str(uuid.uuid4())},
    )
    unknown_field = client.put(
        f"{base(world)}/data-source-policies/salary", headers=admin, json=body
    )

    assert {p["field"] for p in defaults} == set(CONFLICT_FIELDS)
    assert all(not p["configured"] and p["source"] == "syncforge" for p in defaults)
    assert by_manager.status_code == 403  # Organization Admins decide policies
    assert by_admin.status_code == 200 and by_admin.json()["configured"] is True
    assert missing_connector.status_code == 422
    assert foreign.status_code == 404
    assert unknown_field.status_code == 422


def test_api_isolates_organizations(
    client: TestClient,
    db_session: Session,
    world: World,
    mocks: dict[str, RunningMock],
    connector_settings: Settings,
) -> None:
    move_in_google(mocks, world, "Finance")
    service(db_session, connector_settings).reconcile(world.org, world.apps["google_workspace"].id)
    [conflict] = open_conflicts(db_session, world)
    other = create_organization(db_session)
    outsider = create_user(db_session)
    add_member(db_session, outsider, other, OrganizationRole.ORG_ADMIN)
    headers = auth_headers(outsider)

    assert (
        client.get(f"/api/v1/organizations/{other.id}/conflicts", headers=headers).json()["total"]
        == 0
    )
    detail = client.get(
        f"/api/v1/organizations/{other.id}/conflicts/{conflict.id}", headers=headers
    )
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "conflict_not_found"
