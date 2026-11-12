"""The fields SyncForge compares between its employee record and each application.

Pure functions (no I/O), unit-tested on their own.

* `syncforge_values(employee)` and `external_values(user)` render both sides as text;
* `differences(...)` lists the fields that disagree. A field the application does not
  report (None) is not compared - an application that has no "location" is not in
  conflict about it. E-mail, department and designation compare case-insensitively and
  ignore surrounding spaces: "engineering " and "Engineering" are the same department.
* `DEFAULT_POLICIES`: what applies when an organization has not configured a field. HR
  (SyncForge) is authoritative for everything by default and every conflict waits for a
  person; organizations change this per field (e.g. make their identity provider
  authoritative for `account_active`, or let department fixes apply automatically).
"""

from dataclasses import dataclass

from app.connectors.base import ExternalUser
from app.models import (
    ConflictSeverity,
    Employee,
    EmploymentStatus,
    PolicySource,
    ResolutionMode,
)
from app.models.conflict import CONFLICT_FIELDS

CASE_INSENSITIVE = frozenset({"email", "department", "designation", "location"})
# Values that may appear in audit entries (not personal data).
NON_PERSONAL = frozenset({"department", "designation", "location", "account_active"})


@dataclass(frozen=True)
class EffectivePolicy:
    field: str
    source: PolicySource
    connector_id: object | None  # uuid.UUID when source is CONNECTOR
    resolution_mode: ResolutionMode
    severity: ConflictSeverity
    configured: bool  # False: the built-in default


_MANUAL = ResolutionMode.MANUAL
_HR = PolicySource.SYNCFORGE
DEFAULT_POLICIES: dict[str, tuple[PolicySource, ResolutionMode, ConflictSeverity]] = {
    "first_name": (_HR, _MANUAL, ConflictSeverity.LOW),
    "last_name": (_HR, _MANUAL, ConflictSeverity.LOW),
    "email": (_HR, _MANUAL, ConflictSeverity.HIGH),
    "department": (_HR, _MANUAL, ConflictSeverity.MEDIUM),
    "designation": (_HR, _MANUAL, ConflictSeverity.LOW),
    "location": (_HR, _MANUAL, ConflictSeverity.LOW),
    "account_active": (_HR, _MANUAL, ConflictSeverity.HIGH),
}


def _flag(value: bool) -> str:
    return "true" if value else "false"


def syncforge_values(employee: Employee) -> dict[str, str | None]:
    return {
        "first_name": employee.first_name,
        "last_name": employee.last_name,
        "email": employee.email,
        "department": employee.department.name if employee.department else None,
        "designation": employee.designation,
        "location": employee.location,
        # Everyone who is not terminated should have an active account.
        "account_active": _flag(employee.employment_status is not EmploymentStatus.TERMINATED),
    }


def external_values(user: ExternalUser) -> dict[str, str | None]:
    return {
        "first_name": user.first_name or None,
        "last_name": user.last_name or None,
        "email": user.email or None,
        "department": user.department,
        "designation": user.designation,
        "location": user.location,
        "account_active": _flag(user.active),
    }


def _normalized(field: str, value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value.lower() if field in CASE_INSENSITIVE else value


def differences(
    ours: dict[str, str | None], theirs: dict[str, str | None]
) -> dict[str, tuple[str | None, str | None]]:
    """Fields that disagree -> (SyncForge value, application value)."""
    found = {}
    for field in CONFLICT_FIELDS:
        external = theirs.get(field)
        if external is None:
            continue  # not reported by this application
        if _normalized(field, ours.get(field)) != _normalized(field, external):
            found[field] = (ours.get(field), external)
    return found


def severity_for(
    field: str, policy: EffectivePolicy, ours: str | None, theirs: str | None
) -> ConflictSeverity:
    """The policy's severity, escalated for the one case that is a security problem: a
    terminated person whose account is still active."""
    if field == "account_active" and ours == "false" and theirs == "true":
        return ConflictSeverity.CRITICAL
    return policy.severity
