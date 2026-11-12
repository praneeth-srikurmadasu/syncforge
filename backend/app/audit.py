"""Record audit entries (app/models/audit.py).

`record()` stages one entry in the caller's session; the caller's commit makes it
durable together with the change it describes. The actor comes from the session: the
API's authentication dependency stores the authenticated user's ID in
`session.info["actor_user_id"]` (a per-session dict, safe across FastAPI's thread
pool); sessions without it - workers, the relay, CLI commands - record the system as
the actor.

What is recorded, and what never is:

* IDs, action names, outcomes, changed field **names**, error categories and codes;
* old/new values only for non-personal employee fields (department, designation,
  location, employment status, dates, manager) - names, e-mail addresses and employee
  numbers appear as field names only;
* never passwords, tokens, credentials, connector config values or request payloads.
"""

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.request_context import get_request_id
from app.models import ActorType, AuditLog, AuditOutcome

ACTOR_KEY = "actor_user_id"

# Employee fields whose values may appear in audit details (not personal data).
NON_PERSONAL_FIELDS = frozenset(
    {
        "department_id",
        "designation",
        "manager_id",
        "location",
        "employment_status",
        "joining_date",
        "termination_date",
        "archived_at",
    }
)


def set_actor(session: Session, user_id: uuid.UUID | None) -> None:
    session.info[ACTOR_KEY] = user_id


def record(
    session: Session,
    *,
    organization_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditLog:
    actor = session.info.get(ACTOR_KEY)
    entry = AuditLog(
        organization_id=organization_id,
        actor_type=ActorType.USER if actor else ActorType.SYSTEM,
        actor_user_id=actor,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        outcome=outcome,
        details=_jsonable(details or {}),
        request_id=request_id or get_request_id(),
    )
    session.add(entry)
    return entry


def field_changes(changes: dict[str, tuple[Any, Any]]) -> dict[str, Any]:
    """Audit details for an employee change: every changed field by name, values only
    for non-personal fields."""
    return {
        "changed_fields": sorted(changes),
        "values": {
            name: {"from": old, "to": new}
            for name, (old, new) in sorted(changes.items())
            if name in NON_PERSONAL_FIELDS
        },
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value
