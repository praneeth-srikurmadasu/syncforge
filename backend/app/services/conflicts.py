"""Data integrity use cases: policies, reconciliation (conflict detection) and resolution.

Reconciliation (`reconcile`) reads every account linked to one connector from the
external application and compares it field by field with SyncForge's employee record
(app/integrity/fields.py). A difference never overwrites anything by itself:

* it opens (or refreshes) a `data_conflicts` row, with the authoritative side and the
  severity taken from the field's policy;
* if the policy's mode is `auto`, the authoritative side's value is applied at once -
  pushed to the application, or adopted in SyncForge - and the resolution is recorded
  as automatic;
* a field that agrees again closes its open conflict (`no_longer_different`).

Resolution (`resolve`) by a person:

* `use_syncforge` pushes SyncForge's value to the application (`update_user`, or
  `deactivate_user` for an account that should not be active);
* `use_external` adopts the application's value in SyncForge through the normal
  employee update - so it is versioned, audited, and emits events that propagate the
  value to the other applications;
* `dismiss` records an accepted difference and changes nothing.

Rules that protect against wrong or outdated decisions:

* choosing the side the policy does **not** name as authoritative needs
  `override: true` and a note (`422 resolution_against_policy` otherwise);
* `dismiss` needs a note;
* if SyncForge's value changed since the conflict was detected, the decision was made on
  outdated information: `409 conflict_stale` (run reconciliation again);
* adopting a value into SyncForge needs `employees:write` as well;
* a conflict that is no longer open cannot be resolved again (`409 conflict_not_open`).
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.connectors.errors import ConnectorError
from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    PreconditionFailedError,
    UnprocessableError,
)
from app.integrity.fields import (
    DEFAULT_POLICIES,
    NON_PERSONAL,
    EffectivePolicy,
    differences,
    external_values,
    severity_for,
    syncforge_values,
)
from app.models import (
    CONFLICT_FIELDS,
    AuditOutcome,
    ConflictResolution,
    ConflictSeverity,
    ConflictStatus,
    Connector,
    ConnectorStatus,
    DataConflict,
    DataSourcePolicy,
    Department,
    Employee,
    ExternalAccount,
    ExternalAccountStatus,
    Organization,
    PolicySource,
    ResolutionKind,
    ResolutionMode,
    User,
)
from app.services.connectors import ConnectorService
from app.services.employees import EmployeeService

logger = logging.getLogger("syncforge.integrity")

# One synchronous run; larger tenants would page through (docs/data-integrity.md).
MAX_ACCOUNTS_PER_RUN = 500


@dataclass
class ReconcileResult:
    connector_id: uuid.UUID
    accounts_checked: int = 0
    conflicts_opened: int = 0
    conflicts_refreshed: int = 0
    conflicts_closed: int = 0
    auto_resolved: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


class ConflictService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.connectors = ConnectorService(session, self.settings)

    # ---- policies ------------------------------------------------------------------

    def policies(self, organization: Organization) -> dict[str, EffectivePolicy]:
        rows = {
            row.field: row
            for row in self.session.scalars(
                select(DataSourcePolicy).where(DataSourcePolicy.organization_id == organization.id)
            )
        }
        effective = {}
        for name in CONFLICT_FIELDS:
            row = rows.get(name)
            if row is not None:
                effective[name] = EffectivePolicy(
                    name, row.source, row.connector_id, row.resolution_mode, row.severity, True
                )
            else:
                source, mode, severity = DEFAULT_POLICIES[name]
                effective[name] = EffectivePolicy(name, source, None, mode, severity, False)
        return effective

    def set_policy(
        self,
        organization: Organization,
        field_name: str,
        *,
        source: PolicySource,
        connector_id: uuid.UUID | None,
        resolution_mode: ResolutionMode,
        severity: ConflictSeverity,
    ) -> EffectivePolicy:
        if field_name not in CONFLICT_FIELDS:
            raise NotFoundError("Unknown field.", code="field_not_found")
        if (source is PolicySource.CONNECTOR) != (connector_id is not None):
            raise UnprocessableError(
                "connector_id is required when source is 'connector', and only then.",
                code="invalid_policy",
            )
        if connector_id is not None:
            self.connectors.get(organization, connector_id)  # 404 for another org's ID
        row = self.session.scalar(
            select(DataSourcePolicy)
            .where(
                DataSourcePolicy.organization_id == organization.id,
                DataSourcePolicy.field == field_name,
            )
            .with_for_update()
        )
        if row is None:
            row = DataSourcePolicy(organization_id=organization.id, field=field_name)
            self.session.add(row)
        row.source = source
        row.connector_id = connector_id
        row.resolution_mode = resolution_mode
        row.severity = severity
        audit.record(
            self.session,
            organization_id=organization.id,
            action="data_source_policy.updated",
            resource_type="data_source_policy",
            resource_id=field_name,
            details={
                "field": field_name,
                "source": source,
                "connector_id": connector_id,
                "resolution_mode": resolution_mode,
                "severity": severity,
            },
        )
        try:
            self.session.commit()
        except IntegrityError as exc:  # a concurrent request created the same row
            self.session.rollback()
            raise ConflictError("The policy was changed concurrently; retry.") from exc
        return self.policies(organization)[field_name]

    # ---- reconciliation ------------------------------------------------------------

    def reconcile(self, organization: Organization, connector_id: uuid.UUID) -> ReconcileResult:
        connector = self.connectors.get(organization, connector_id)
        if connector.status is ConnectorStatus.DISCONNECTED:
            raise ConflictError("Reconnect the connector first.", code="connector_disconnected")
        policies = self.policies(organization)
        result = ReconcileResult(connector_id=connector.id)
        accounts = list(
            self.session.scalars(
                select(ExternalAccount)
                .where(
                    ExternalAccount.organization_id == organization.id,
                    ExternalAccount.connector_id == connector.id,
                )
                .order_by(ExternalAccount.created_at, ExternalAccount.id)
                .limit(MAX_ACCOUNTS_PER_RUN)
            )
        )
        for account in accounts:
            employee = self.session.get(Employee, account.employee_id)
            try:
                user = self.connectors.read_external_user(connector, account.external_id)
            except (ConnectorError, AppError) as error:
                category = getattr(error, "category", None)
                result.errors.append(
                    {
                        "employee_id": str(account.employee_id),
                        "category": category.value if category else "configuration",
                        "code": error.code,
                    }
                )
                if category is not None and category.value == "circuit_open":
                    break  # the application is down: stop asking it
                continue
            result.accounts_checked += 1
            self._compare(organization, connector, employee, user, policies, result)
        audit.record(
            self.session,
            organization_id=organization.id,
            action="connector.reconciled",
            resource_type="connector",
            resource_id=connector.id,
            outcome=AuditOutcome.FAILURE if result.errors else AuditOutcome.SUCCESS,
            details={
                "accounts_checked": result.accounts_checked,
                "conflicts_opened": result.conflicts_opened,
                "conflicts_refreshed": result.conflicts_refreshed,
                "conflicts_closed": result.conflicts_closed,
                "auto_resolved": result.auto_resolved,
                "errors": len(result.errors),
            },
        )
        self.session.commit()
        logger.info(
            "reconciliation finished",
            extra={
                "organization_id": str(organization.id),
                "connector_id": str(connector.id),
                "accounts_checked": result.accounts_checked,
                "conflicts_opened": result.conflicts_opened,
                "errors": len(result.errors),
            },
        )
        return result

    def _compare(
        self,
        organization: Organization,
        connector: Connector,
        employee: Employee,
        user: Any,
        policies: dict[str, EffectivePolicy],
        result: ReconcileResult,
    ) -> None:
        ours = syncforge_values(employee)
        found = differences(ours, external_values(user))
        open_conflicts = {
            c.field: c
            for c in self.session.scalars(
                select(DataConflict).where(
                    DataConflict.employee_id == employee.id,
                    DataConflict.connector_id == connector.id,
                    DataConflict.status == ConflictStatus.OPEN,
                )
            )
        }
        now = _now()
        for name, existing in open_conflicts.items():
            if name not in found:  # agrees again (fixed elsewhere)
                self._close(existing, ResolutionKind.NO_LONGER_DIFFERENT, None, automatic=True)
                result.conflicts_closed += 1
        for name, (syncforge_value, external_value) in found.items():
            policy = policies[name]
            authority = self._authority(policy, connector)
            severity = severity_for(name, policy, syncforge_value, external_value)
            conflict = open_conflicts.get(name)
            if conflict is None:
                conflict = DataConflict(
                    organization_id=organization.id,
                    employee_id=employee.id,
                    connector_id=connector.id,
                    field=name,
                    first_detected_at=now,
                    times_detected=1,
                )
                self.session.add(conflict)
                result.conflicts_opened += 1
                is_new = True
            else:
                conflict.times_detected += 1
                result.conflicts_refreshed += 1
                is_new = False
            conflict.syncforge_value = syncforge_value
            conflict.external_value = external_value
            conflict.authoritative_source = authority
            conflict.severity = severity
            conflict.employee_version = employee.version
            conflict.last_detected_at = now
            self.session.flush()
            if is_new:
                self._audit(
                    conflict,
                    "conflict.detected",
                    {"severity": severity, "authoritative_source": authority},
                    outcome=AuditOutcome.FAILURE,
                )
            if policy.resolution_mode is ResolutionMode.AUTO:
                self.session.commit()
                if self._auto_resolve(organization, conflict, connector, employee):
                    result.auto_resolved += 1

    @staticmethod
    def _authority(policy: EffectivePolicy, connector: Connector) -> PolicySource:
        """The connector being compared is authoritative only if the policy names it;
        against every other application, SyncForge's record is the reference."""
        if policy.source is PolicySource.CONNECTOR and policy.connector_id == connector.id:
            return PolicySource.CONNECTOR
        return PolicySource.SYNCFORGE

    def _auto_resolve(
        self,
        organization: Organization,
        conflict: DataConflict,
        connector: Connector,
        employee: Employee,
    ) -> bool:
        kind = (
            ResolutionKind.USE_EXTERNAL
            if conflict.authoritative_source is PolicySource.CONNECTOR
            else ResolutionKind.USE_SYNCFORGE
        )
        try:
            applied = self._apply(organization, conflict, connector, employee, kind)
        except AppError as error:  # stays open for a person; the error is logged
            self.session.rollback()
            logger.warning(
                "automatic conflict resolution failed",
                extra={"conflict_id": str(conflict.id), "code": error.code},
            )
            return False
        conflict = self.session.get(DataConflict, conflict.id)
        self._close(conflict, kind, applied, automatic=True)
        self.session.commit()
        return True

    # ---- resolution ----------------------------------------------------------------

    def get(self, organization: Organization, conflict_id: uuid.UUID) -> DataConflict:
        conflict = self.session.scalar(
            select(DataConflict).where(
                DataConflict.organization_id == organization.id, DataConflict.id == conflict_id
            )
        )
        if conflict is None:
            raise NotFoundError("Conflict not found.", code="conflict_not_found")
        return conflict

    def resolve(
        self,
        organization: Organization,
        conflict_id: uuid.UUID,
        *,
        resolution: ResolutionKind,
        actor: User,
        note: str | None,
        override: bool,
        can_write_employees: bool,
    ) -> DataConflict:
        conflict = self.session.scalar(
            select(DataConflict)
            .where(DataConflict.organization_id == organization.id, DataConflict.id == conflict_id)
            .with_for_update()
        )
        if conflict is None:
            raise NotFoundError("Conflict not found.", code="conflict_not_found")
        if conflict.status is not ConflictStatus.OPEN:
            self.session.rollback()
            raise ConflictError(
                f"This conflict is already {conflict.status.value}.", code="conflict_not_open"
            )
        if resolution is ResolutionKind.NO_LONGER_DIFFERENT:
            raise UnprocessableError(
                "This outcome is recorded by reconciliation, not chosen.", code="invalid_resolution"
            )

        against_policy = False
        if resolution is ResolutionKind.DISMISS:
            if not note:
                raise UnprocessableError(
                    "Dismissing a conflict needs a note.", code="note_required"
                )
        else:
            authoritative = (
                ResolutionKind.USE_EXTERNAL
                if conflict.authoritative_source is PolicySource.CONNECTOR
                else ResolutionKind.USE_SYNCFORGE
            )
            against_policy = resolution is not authoritative
            if against_policy and not override:
                raise UnprocessableError(
                    "The policy names the other side as authoritative for this field. Send "
                    "override: true and a note to decide against it.",
                    code="resolution_against_policy",
                    details={"authoritative": conflict.authoritative_source},
                )
            if against_policy and not note:
                raise UnprocessableError(
                    "Deciding against the policy needs a note.", code="note_required"
                )
        if (
            resolution is ResolutionKind.USE_EXTERNAL
            and conflict.field != "account_active"
            and not can_write_employees
        ):
            raise PermissionDeniedError(
                "Adopting a value into the employee record needs permission to edit employees.",
                code="permission_denied",
            )

        employee = self.session.get(Employee, conflict.employee_id)
        if syncforge_values(employee)[conflict.field] != conflict.syncforge_value:
            self.session.rollback()
            raise ConflictError(
                "The employee changed since this conflict was detected. Run reconciliation "
                "again and decide on the current values.",
                code="conflict_stale",
            )
        connector = self.session.get(Connector, conflict.connector_id)

        applied = None
        if resolution is not ResolutionKind.DISMISS:
            applied = self._apply(organization, conflict, connector, employee, resolution)
        # The external call or the employee update committed (releasing our row lock):
        # lock again. If someone resolved it meanwhile, their (identical) outcome stands.
        conflict = self.session.scalar(
            select(DataConflict).where(DataConflict.id == conflict_id).with_for_update()
        )
        if conflict.status is ConflictStatus.OPEN:
            self._close(
                conflict,
                resolution,
                applied,
                automatic=False,
                actor=actor,
                note=note,
                against_policy=against_policy,
            )
        self.session.commit()
        return conflict

    def _apply(
        self,
        organization: Organization,
        conflict: DataConflict,
        connector: Connector,
        employee: Employee,
        resolution: ResolutionKind,
    ) -> str | None:
        """Make both sides agree. Returns the value that now holds on both sides."""
        if resolution is ResolutionKind.USE_SYNCFORGE:
            if conflict.field == "account_active":
                if conflict.syncforge_value == "true":
                    raise UnprocessableError(
                        "Reactivating an account in the application is not supported by the "
                        "connectors; reactivate it there, or adopt its state.",
                        code="reactivation_not_supported",
                    )
                self.connectors.run_operation(
                    organization, connector.id, operation="deactivate_user", employee_id=employee.id
                )
            else:
                # update_user sends the whole profile, so every field becomes SyncForge's.
                self.connectors.run_operation(
                    organization, connector.id, operation="update_user", employee_id=employee.id
                )
            return conflict.syncforge_value

        # USE_EXTERNAL
        value = conflict.external_value
        if conflict.field == "account_active":
            account = self.session.scalar(
                select(ExternalAccount).where(
                    ExternalAccount.connector_id == connector.id,
                    ExternalAccount.employee_id == employee.id,
                )
            )
            if account is not None:
                account.status = (
                    ExternalAccountStatus.ACTIVE
                    if value == "true"
                    else ExternalAccountStatus.DEACTIVATED
                )
            return value
        if conflict.field == "department":
            department = self.session.scalar(
                select(Department).where(
                    Department.organization_id == organization.id,
                    Department.name.ilike(value.strip()),
                )
            )
            if department is None:
                raise UnprocessableError(
                    f"SyncForge has no department named '{value}'. Create it first.",
                    code="department_not_found",
                )
            changes = {"department_id": department.id}
        elif conflict.field == "email":
            changes = {"email": value.strip().lower()}
        else:
            changes = {conflict.field: value.strip()}
        try:
            EmployeeService(self.session).update(
                organization, employee.id, changes, expected_version=conflict.employee_version
            )
        except PreconditionFailedError as exc:
            raise ConflictError(
                "The employee changed since this conflict was detected. Run reconciliation "
                "again and decide on the current values.",
                code="conflict_stale",
            ) from exc
        return value

    def _close(
        self,
        conflict: DataConflict,
        resolution: ResolutionKind,
        applied: str | None,
        *,
        automatic: bool,
        actor: User | None = None,
        note: str | None = None,
        against_policy: bool = False,
    ) -> None:
        conflict.status = (
            ConflictStatus.DISMISSED
            if resolution is ResolutionKind.DISMISS
            else ConflictStatus.RESOLVED
        )
        conflict.resolved_at = _now()
        self.session.add(
            ConflictResolution(
                organization_id=conflict.organization_id,
                conflict_id=conflict.id,
                resolution=resolution,
                applied_value=applied,
                against_policy=against_policy,
                automatic=automatic,
                note=note,
                resolved_by_user_id=actor.id if actor else None,
            )
        )
        self._audit(
            conflict,
            "conflict.dismissed" if resolution is ResolutionKind.DISMISS else "conflict.resolved",
            {
                "resolution": resolution,
                "automatic": automatic,
                "against_policy": against_policy,
                **({"applied_value": applied} if conflict.field in NON_PERSONAL else {}),
            },
        )

    def _audit(
        self,
        conflict: DataConflict,
        action: str,
        details: dict[str, Any],
        *,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
    ) -> None:
        values = (
            {"syncforge_value": conflict.syncforge_value, "external_value": conflict.external_value}
            if conflict.field in NON_PERSONAL
            else {}
        )
        audit.record(
            self.session,
            organization_id=conflict.organization_id,
            action=action,
            resource_type="data_conflict",
            resource_id=conflict.id,
            outcome=outcome,
            details={
                "employee_id": conflict.employee_id,
                "connector_id": conflict.connector_id,
                "field": conflict.field,
                **values,
                **details,
            },
        )

    def resolutions(self, conflict: DataConflict) -> list[ConflictResolution]:
        return list(
            self.session.scalars(
                select(ConflictResolution)
                .where(ConflictResolution.conflict_id == conflict.id)
                .order_by(ConflictResolution.created_at)
            )
        )
