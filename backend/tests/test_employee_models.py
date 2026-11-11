"""Database rules for departments and employees, including tenant integrity."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import EmploymentStatus
from tests.factories import create_department, create_employee, create_organization


def test_employee_defaults_and_relationships(db_session: Session) -> None:
    org = create_organization(db_session)
    engineering = create_department(db_session, org, "Engineering")
    manager = create_employee(db_session, org, first_name="Ada", department=engineering)
    report = create_employee(db_session, org, manager=manager, department=engineering)
    db_session.expire_all()

    assert report.employment_status is EmploymentStatus.ACTIVE
    assert report.archived_at is None
    assert report.department.name == "Engineering"
    assert report.manager.id == manager.id
    assert report.full_name == "Grace Hopper"


# ---- uniqueness is per organization --------------------------------------------------


def test_employee_number_unique_within_an_organization(db_session: Session) -> None:
    org = create_organization(db_session)
    create_employee(db_session, org, employee_number="E-1001")

    with pytest.raises(IntegrityError, match="uq_employees_organization_id_employee_number"):
        create_employee(db_session, org, employee_number="E-1001")


def test_email_unique_within_an_organization(db_session: Session) -> None:
    org = create_organization(db_session)
    create_employee(db_session, org, email="grace@acme.example")

    with pytest.raises(IntegrityError, match="uq_employees_organization_id_email"):
        create_employee(db_session, org, email="grace@acme.example")


def test_same_employee_number_and_email_allowed_in_different_organizations(
    db_session: Session,
) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)

    create_employee(db_session, acme, employee_number="E-1", email="sam@shared.example")
    create_employee(db_session, globex, employee_number="E-1", email="sam@shared.example")


def test_department_names_are_unique_per_organization_ignoring_case(db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    create_department(db_session, acme, "Engineering")
    create_department(db_session, globex, "engineering")  # other org: allowed

    with pytest.raises(IntegrityError, match="uq_departments_organization_id_lower_name"):
        create_department(db_session, acme, "ENGINEERING")


# ---- tenant integrity: composite foreign keys ----------------------------------------


def test_cannot_use_another_organizations_department(db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    globex_sales = create_department(db_session, globex, "Sales")

    with pytest.raises(IntegrityError, match="fk_employees_department_same_organization"):
        create_employee(db_session, acme, department=globex_sales)


def test_cannot_use_another_organizations_manager(db_session: Session) -> None:
    acme, globex = create_organization(db_session), create_organization(db_session)
    globex_boss = create_employee(db_session, globex)

    with pytest.raises(IntegrityError, match="fk_employees_manager_same_organization"):
        create_employee(db_session, acme, manager=globex_boss)


def test_department_in_use_cannot_be_deleted(db_session: Session) -> None:
    org = create_organization(db_session)
    sales = create_department(db_session, org, "Sales")
    create_employee(db_session, org, department=sales)

    with pytest.raises(IntegrityError, match="fk_employees_department_same_organization"):
        db_session.execute(text("DELETE FROM departments WHERE id = :id"), {"id": sales.id})


# ---- lifecycle rules -----------------------------------------------------------------


def test_employee_cannot_manage_themselves(db_session: Session) -> None:
    org = create_organization(db_session)
    employee = create_employee(db_session, org)
    employee.manager_id = employee.id

    with pytest.raises(IntegrityError, match="ck_employees_not_own_manager"):
        db_session.flush()


def test_terminated_employee_requires_termination_date(db_session: Session) -> None:
    org = create_organization(db_session)

    with pytest.raises(IntegrityError, match="ck_employees_termination_date_matches_status"):
        create_employee(db_session, org, employment_status=EmploymentStatus.TERMINATED)


def test_active_employee_cannot_have_termination_date(db_session: Session) -> None:
    org = create_organization(db_session)

    with pytest.raises(IntegrityError, match="ck_employees_termination_date_matches_status"):
        create_employee(db_session, org, termination_date=date(2025, 1, 1))


def test_termination_cannot_precede_joining(db_session: Session) -> None:
    org = create_organization(db_session)

    with pytest.raises(IntegrityError, match="ck_employees_termination_not_before_joining"):
        create_employee(
            db_session,
            org,
            employment_status=EmploymentStatus.TERMINATED,
            joining_date=date(2025, 6, 1),
            termination_date=date(2025, 5, 31),
        )


def test_unknown_employment_status_is_rejected(db_session: Session) -> None:
    org = create_organization(db_session)

    with pytest.raises(IntegrityError, match="ck_employees_employment_status"):
        db_session.execute(
            text(
                "INSERT INTO employees (id, organization_id, employee_number, first_name, "
                "last_name, email, employment_status, joining_date) VALUES (:id, :org, 'E-9', "
                "'X', 'Y', 'x@y.example', 'retired', '2024-01-01')"
            ),
            {"id": uuid.uuid4(), "org": org.id},
        )


def test_deleting_organization_removes_its_employees_and_departments(db_session: Session) -> None:
    org = create_organization(db_session)
    dept = create_department(db_session, org, "Ops")
    boss = create_employee(db_session, org, department=dept)
    create_employee(db_session, org, department=dept, manager=boss)

    db_session.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org.id})

    remaining = db_session.execute(
        text("SELECT (SELECT count(*) FROM employees), (SELECT count(*) FROM departments)")
    ).one()
    assert tuple(remaining) == (0, 0)
