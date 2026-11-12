"""Department and employee request/response schemas.

Validation happens here (shape, lengths, formats). Business rules that need the
database - same-organization references, manager cycles, lifecycle state - are
enforced in app/services/employees.py.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import EmploymentStatus

DepartmentName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
EmployeeNumber = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
    ),
]
OptionalText = Annotated[
    str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
# Employment status a client may set directly. Termination has its own endpoint
# because it has side effects (reassigning direct reports) and is final.
SettableStatus = Literal[EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE]


def _lower_email(value: str) -> str:
    return value.lower()


# ---- departments ---------------------------------------------------------------------


class DepartmentCreate(BaseModel):
    name: DepartmentName

    model_config = ConfigDict(json_schema_extra={"example": {"name": "Engineering"}})


class DepartmentUpdate(BaseModel):
    name: DepartmentName


class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    employee_count: int = Field(description="Employees in this department, including archived.")
    created_at: datetime


# ---- employees: requests -------------------------------------------------------------


class EmployeeCreate(BaseModel):
    employee_number: EmployeeNumber = Field(description="HR system identifier, e.g. E-1001.")
    first_name: PersonName
    last_name: PersonName
    email: EmailStr
    department_id: uuid.UUID | None = None
    designation: OptionalText = None
    manager_id: uuid.UUID | None = None
    location: OptionalText = None
    employment_status: SettableStatus = EmploymentStatus.ACTIVE
    joining_date: date

    _email = field_validator("email")(_lower_email)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_number": "E-1001",
                "first_name": "Grace",
                "last_name": "Hopper",
                "email": "grace.hopper@acme.example",
                "designation": "Staff Engineer",
                "location": "Bengaluru",
                "joining_date": "2024-01-15",
            }
        }
    )


class EmployeeUpdate(BaseModel):
    """Partial update: only the fields present in the request body are changed.

    Optional fields (department, manager, designation, location) can be cleared by
    sending null. Required fields cannot be null.
    """

    employee_number: EmployeeNumber | None = None
    first_name: PersonName | None = None
    last_name: PersonName | None = None
    email: EmailStr | None = None
    department_id: uuid.UUID | None = None
    designation: OptionalText = None
    manager_id: uuid.UUID | None = None
    location: OptionalText = None
    employment_status: SettableStatus | None = None
    joining_date: date | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"designation": "Principal Engineer", "location": "Pune"}},
    )

    _NOT_NULLABLE = frozenset(
        {
            "employee_number",
            "first_name",
            "last_name",
            "email",
            "employment_status",
            "joining_date",
        }
    )

    @field_validator("email")
    @classmethod
    def _email_lower(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else None

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> "EmployeeUpdate":
        nulled = sorted(
            name
            for name in self.model_fields_set & self._NOT_NULLABLE
            if getattr(self, name) is None
        )
        if nulled:
            raise ValueError(f"These fields cannot be null: {', '.join(nulled)}")
        return self

    def changes(self) -> dict[str, Any]:
        """Only the fields the client actually sent."""
        return self.model_dump(include=self.model_fields_set)


class EmployeeTerminate(BaseModel):
    termination_date: date | None = Field(
        default=None, description="Last working day. Defaults to today (UTC)."
    )


# ---- employees: responses ------------------------------------------------------------


class DepartmentRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class ManagerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_number: str
    full_name: str


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    employee_number: str
    first_name: str
    last_name: str
    full_name: str
    email: str
    department: DepartmentRef | None
    designation: str | None
    manager: ManagerRef | None
    location: str | None
    employment_status: EmploymentStatus
    joining_date: date
    termination_date: date | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int = Field(
        description="Incremented on every change; also sent as the ETag header. Send it "
        "back in If-Match when changing the employee to avoid overwriting someone else's "
        "change."
    )
