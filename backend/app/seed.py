"""Realistic demo data for local development.

    python -m app.cli seed-demo --admin-email you@example.com

Creates one organization ("Acme Demo", slug acme-demo) with five departments and a
small reporting hierarchy, and makes the given (already registered) user its
Organization Admin. All names and emails are fictional (example.com domain).

Everything is created through the same services the API uses, so every business rule
(uniqueness, same-organization references, no cycles, termination side effects)
applies to the seed data too, and lifecycle events are emitted as usual.

No passwords are involved: register your user through the API first.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models import Employee, Organization, OrganizationMembership, OrganizationRole
from app.repositories.organizations import OrganizationRepository
from app.repositories.users import UserRepository
from app.schemas.employees import EmployeeCreate
from app.services.employees import DepartmentService, EmployeeService

DEMO_SLUG = "acme-demo"
DEMO_NAME = "Acme Demo"
DEPARTMENTS = ("Engineering", "Product", "Sales", "People Operations", "Finance")


@dataclass(frozen=True)
class DemoPerson:
    number: str
    first: str
    last: str
    department: str
    designation: str
    location: str
    joined: date
    manager: str | None  # employee number of the manager


# number | first | last | department | designation | location | joined | manager
# Ordered so every manager is created before their reports.
_PEOPLE_TABLE = """
AC-001 | Meera | Iyer | Engineering | Chief Executive Officer | Bengaluru | 2019-04-01
AC-002 | Rohan | Kapoor | Engineering | VP Engineering | Bengaluru | 2019-09-16 | AC-001
AC-003 | Ananya | Rao | Product | Head of Product | Hyderabad | 2020-02-03 | AC-001
AC-004 | Vikram | Shah | Sales | Head of Sales | Pune | 2020-07-01 | AC-001
AC-005 | Farah | Khan | People Operations | HR Director | Bengaluru | 2020-11-09 | AC-001
AC-006 | Arjun | Menon | Finance | Finance Manager | Bengaluru | 2021-01-18 | AC-001
AC-007 | Kavya | Nair | Engineering | Engineering Manager | Bengaluru | 2021-03-22 | AC-002
AC-008 | Siddharth | Joshi | Engineering | Senior Engineer | Bengaluru | 2021-06-14 | AC-007
AC-009 | Priya | Reddy | Engineering | Software Engineer | Hyderabad | 2022-08-01 | AC-007
AC-010 | Aditya | Verma | Engineering | Software Engineer | Remote | 2023-01-09 | AC-007
AC-011 | Neha | Gupta | Engineering | Site Reliability Engineer | Pune | 2022-04-25 | AC-002
AC-012 | Karthik | Subramanian | Product | Product Manager | Hyderabad | 2022-10-03 | AC-003
AC-013 | Ishita | Banerjee | Product | Product Designer | Remote | 2023-05-15 | AC-003
AC-014 | Rahul | Desai | Sales | Account Executive | Pune | 2022-02-07 | AC-004
AC-015 | Sneha | Pillai | Sales | Account Executive | Bengaluru | 2023-07-03 | AC-004
AC-016 | Manish | Agarwal | Sales | Sales Development Rep | Pune | 2024-01-15 | AC-014
AC-017 | Divya | Krishnan | People Operations | HR Partner | Bengaluru | 2023-03-20 | AC-005
AC-018 | Tanvi | Mehta | Finance | Payroll Specialist | Bengaluru | 2023-09-04 | AC-006
AC-019 | Nikhil | Chopra | Engineering | QA Engineer | Remote | 2024-06-10 | AC-007
AC-020 | Pooja | Saxena | Sales | Account Executive | Pune | 2024-02-12 | AC-004
"""


def _parse(table: str) -> tuple[DemoPerson, ...]:
    people = []
    for line in table.strip().splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        number, first, last, department, designation, location, joined = cells[:7]
        manager = cells[7] if len(cells) > 7 else None
        people.append(
            DemoPerson(
                number,
                first,
                last,
                department,
                designation,
                location,
                date.fromisoformat(joined),
                manager,
            )
        )
    return tuple(people)


PEOPLE = _parse(_PEOPLE_TABLE)

# Lifecycle variety: one person on leave, one terminated (their reports move up).
ON_LEAVE = "AC-013"
TERMINATED = ("AC-014", date(2026, 6, 30))


@dataclass(frozen=True)
class SeedResult:
    organization: Organization
    departments: int
    employees: int


class SeedError(Exception):
    pass


def seed_demo(session: Session, *, admin_email: str) -> SeedResult:
    organizations = OrganizationRepository(session)
    if organizations.slug_exists(DEMO_SLUG):
        raise SeedError(f"Demo organization '{DEMO_SLUG}' already exists; nothing to do.")
    admin = UserRepository(session).get_by_email(admin_email.strip().lower())
    if admin is None or not admin.is_active:
        raise SeedError(
            f"No active user {admin_email!r}. Register first: POST /api/v1/auth/register."
        )

    organization = Organization(name=DEMO_NAME, slug=DEMO_SLUG)
    organizations.add(organization)
    organizations.add_membership(
        OrganizationMembership(
            organization=organization, user=admin, role=OrganizationRole.ORG_ADMIN
        )
    )
    session.commit()

    department_service = DepartmentService(session)
    department_ids = {
        name: department_service.create(organization, name=name).id for name in DEPARTMENTS
    }

    employee_service = EmployeeService(session)
    created: dict[str, Employee] = {}
    for person in PEOPLE:
        created[person.number] = employee_service.create(
            organization,
            EmployeeCreate(
                employee_number=person.number,
                first_name=person.first,
                last_name=person.last,
                email=f"{person.first}.{person.last}@acme-demo.example.com".lower(),
                department_id=department_ids[person.department],
                designation=person.designation,
                manager_id=created[person.manager].id if person.manager else None,
                location=person.location,
                joining_date=person.joined,
            ),
        )

    employee_service.update(organization, created[ON_LEAVE].id, {"employment_status": "on_leave"})
    number, last_day = TERMINATED
    employee_service.terminate(organization, created[number].id, termination_date=last_day)

    return SeedResult(
        organization=organization, departments=len(DEPARTMENTS), employees=len(PEOPLE)
    )
