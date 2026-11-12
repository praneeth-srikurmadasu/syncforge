"""Connector use cases: configure, test, disconnect, and run operations.

Rules enforced here:
* the connector type must exist in the registry; config and credentials must match its
  schema (validation errors name fields, never values);
* a base-URL override must point at an allowed host (SSRF protection) - checked when
  the connector is saved, and again by the HTTP client on every call;
* credentials are encrypted before they reach the database and never returned;
* changing config or credentials puts the connector back to `pending` until re-tested;
* disconnecting deletes the credentials (access is revoked on our side immediately).

External calls are made without holding database row locks, so a slow external API
cannot block other requests on the same rows. Each operation is synchronous in Phase 4
(admin-triggered); Phase 5 runs them from background workers.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit
from app.connectors import registry
from app.connectors.base import Connector as ConnectorAdapter
from app.connectors.base import ConnectorSpec, ExternalUser, UserProfile
from app.connectors.errors import ConnectorError
from app.connectors.http import check_allowed_url
from app.core.config import Settings, get_settings
from app.core.errors import (
    BadGatewayError,
    ConflictError,
    NotFoundError,
    UnprocessableError,
)
from app.models import (
    AuditOutcome,
    Connector,
    ConnectorCredential,
    ConnectorStatus,
    Employee,
    EmploymentStatus,
    ExternalAccount,
    ExternalAccountStatus,
    Organization,
)
from app.reliability.circuit_breaker import CircuitBreaker
from app.repositories.connectors import ConnectorRepository, ExternalAccountRepository
from app.repositories.employees import EmployeeRepository
from app.security.encryption import CredentialCipher, fingerprint

logger = logging.getLogger("syncforge.connectors")


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    status: ConnectorStatus
    tested_at: datetime
    latency_ms: float | None
    detail: str | None
    error: dict[str, Any] | None


@dataclass(frozen=True)
class OperationResult:
    operation: str
    connector_id: uuid.UUID
    employee_id: uuid.UUID
    external_id: str
    external_active: bool
    account_status: ExternalAccountStatus
    latency_ms: float | None


def profile_from_employee(employee: Employee) -> UserProfile:
    return UserProfile(
        employee_number=employee.employee_number,
        email=employee.email,
        first_name=employee.first_name,
        last_name=employee.last_name,
        active=employee.employment_status is not EmploymentStatus.TERMINATED,
        department=employee.department.name if employee.department else None,
        designation=employee.designation,
        location=employee.location,
    )


def _revealed(model: BaseModel) -> dict[str, Any]:
    """Credential model -> plain dict for encryption (SecretStr values revealed)."""
    return {
        name: value.get_secret_value() if isinstance(value, SecretStr) else value
        for name, value in model
    }


class ConnectorService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.connectors = ConnectorRepository(session)
        self.accounts = ExternalAccountRepository(session)

    # ---- configuration -----------------------------------------------------------

    def get(self, organization: Organization, connector_id: uuid.UUID) -> Connector:
        connector = self.connectors.get(organization.id, connector_id)
        if connector is None:
            raise NotFoundError("Connector not found.", code="connector_not_found")
        return connector

    def create(
        self,
        organization: Organization,
        *,
        connector_type: str,
        name: str,
        config: dict[str, Any],
        credentials: dict[str, Any],
    ) -> Connector:
        spec = self._spec(connector_type)
        normalized_config, secrets = self._validate(spec, config, credentials)
        if self.connectors.name_taken(organization.id, name):
            raise ConflictError(
                "A connector with this name already exists.", code="connector_name_taken"
            )

        connector = Connector(
            organization_id=organization.id,
            connector_type=spec.connector_type,
            connector_version=spec.version,
            name=name,
            config=normalized_config,
            status=ConnectorStatus.PENDING,
        )
        try:
            self.connectors.add(connector)
            self._store_credentials(connector, spec, secrets)
            self.session.flush()
            self._audit(
                connector,
                "connector.created",
                {
                    "connector_type": connector.connector_type,
                    "name": name,
                    "config_keys": sorted(normalized_config),
                },
            )
            self.session.commit()
        except IntegrityError as exc:  # concurrent create with the same name
            self.session.rollback()
            raise ConflictError(
                "A connector with this name already exists.", code="connector_name_taken"
            ) from exc
        self.session.refresh(connector)
        self._log("connector created", connector)
        return connector

    def update(
        self,
        organization: Organization,
        connector_id: uuid.UUID,
        *,
        name: str | None,
        config: dict[str, Any] | None,
        credentials: dict[str, Any] | None,
    ) -> Connector:
        connector = self.connectors.get(organization.id, connector_id, for_update=True)
        if connector is None:
            raise NotFoundError("Connector not found.", code="connector_not_found")
        spec = self._spec(connector.connector_type)
        changed: list[str] = []

        if name is not None and name != connector.name:
            changed.append("name")
            if self.connectors.name_taken(organization.id, name, exclude_id=connector.id):
                raise ConflictError(
                    "A connector with this name already exists.", code="connector_name_taken"
                )
            connector.name = name
        if config is not None or credentials is not None:
            normalized_config, secrets = self._validate(
                spec, connector.config if config is None else config, credentials
            )
            if normalized_config != connector.config:
                changed.append("config")
            connector.config = normalized_config
            if secrets is not None:
                changed.append("credentials")  # rotated; the values are never recorded
                self._store_credentials(connector, spec, secrets)
            # Settings changed: the old test result no longer proves anything.
            connector.status = ConnectorStatus.PENDING
            connector.last_error_category = None
            connector.last_error_message = None
        self._audit(connector, "connector.updated", {"changed": changed})
        self.session.commit()
        self.session.refresh(connector)
        self._log("connector updated", connector)
        return connector

    def disconnect(self, organization: Organization, connector_id: uuid.UUID) -> Connector:
        """Revoke access: delete the stored credentials. Idempotent."""
        connector = self.connectors.get(organization.id, connector_id, for_update=True)
        if connector is None:
            raise NotFoundError("Connector not found.", code="connector_not_found")
        connector.credential = None  # delete-orphan cascade removes the row
        connector.status = ConnectorStatus.DISCONNECTED
        connector.last_error_category = None
        connector.last_error_message = None
        self._audit(connector, "connector.disconnected", {"credentials_deleted": True})
        self.session.commit()
        self.session.refresh(connector)
        self._log("connector disconnected", connector)
        return connector

    # ---- connection test ---------------------------------------------------------

    def test(self, organization: Organization, connector_id: uuid.UUID) -> ConnectionTestResult:
        connector = self.get(organization, connector_id)
        self._ensure_connected(connector)
        tested_at = datetime.now(UTC)
        try:
            adapter = self._adapter(connector)
            try:
                check = adapter.test_connection()
            finally:
                adapter.close()
        except ConnectorError as error:
            self._record_test(connector, tested_at, error)
            self._log("connector test failed", connector, category=error.category.value)
            return ConnectionTestResult(
                ok=False,
                status=connector.status,
                tested_at=tested_at,
                latency_ms=None,
                detail=None,
                error=error.to_dict(),
            )
        self._record_test(connector, tested_at, None)
        CircuitBreaker(self.session, self.settings).reset(connector)
        self._log("connector test succeeded", connector, latency_ms=check.latency_ms)
        return ConnectionTestResult(
            ok=True,
            status=connector.status,
            tested_at=tested_at,
            latency_ms=check.latency_ms,
            detail=check.detail,
            error=None,
        )

    def _record_test(
        self, connector: Connector, tested_at: datetime, error: ConnectorError | None
    ) -> None:
        connector = self.connectors.get(connector.organization_id, connector.id, for_update=True)
        if connector is None:  # deleted meanwhile (organization removed)
            return
        if connector.status is not ConnectorStatus.DISCONNECTED:
            connector.status = ConnectorStatus.ERROR if error else ConnectorStatus.CONNECTED
        connector.last_tested_at = tested_at
        connector.last_error_category = error.category.value if error else None
        connector.last_error_message = error.message[:500] if error else None
        self._audit(
            connector,
            "connector.tested",
            {"error_category": error.category.value, "error_code": error.code} if error else {},
            outcome=AuditOutcome.FAILURE if error else AuditOutcome.SUCCESS,
        )
        self.session.commit()

    # ---- operations --------------------------------------------------------------

    def run_operation(
        self,
        organization: Organization,
        connector_id: uuid.UUID,
        *,
        operation: str,
        employee_id: uuid.UUID,
        idempotency_key: str | None = None,
        audited: bool = False,
    ) -> OperationResult:
        """Run one operation for one employee and record the external account link.

        `idempotency_key` is passed to `create_user` (the one operation that is not
        naturally idempotent); callers that may repeat a call - the workflow engine -
        pass the same key every time. `audited` writes a `connector.operation_run` audit
        entry (manual operations; the workflow engine audits executions itself)."""
        connector = self.get(organization, connector_id)
        employee = EmployeeRepository(self.session).get(organization.id, employee_id)
        if employee is None:
            raise UnprocessableError("Employee not found.", code="employee_not_found")
        account = self.accounts.get(connector.id, employee.id)

        if operation == "create_user":
            if account is not None:
                raise ConflictError(
                    "This employee already has an account in this application.",
                    code="already_linked",
                    details={"external_id": account.external_id},
                )
            if employee.employment_status is EmploymentStatus.TERMINATED:
                raise ConflictError(
                    "Cannot create an account for a terminated employee.",
                    code="employee_terminated",
                )
        elif account is None:
            raise ConflictError(
                "This employee has no account in this application yet (run create_user).",
                code="not_linked",
            )

        profile = profile_from_employee(employee)
        adapter = self._adapter(connector, for_operation=True)
        breaker = CircuitBreaker(self.session, self.settings)
        try:
            breaker.before_call(connector)  # raises circuit_open while the breaker is open
        except ConnectorError as error:
            adapter.close()
            self._log(
                "connector operation refused",
                connector,
                operation=operation,
                category=error.category.value,
            )
            raise BadGatewayError(
                f"{connector.name}: {error.message}", details=error.to_dict()
            ) from error
        try:
            if operation == "create_user":
                external = adapter.create_user(profile, idempotency_key=idempotency_key)
            elif operation == "update_user":
                external = adapter.update_user(account.external_id, profile)
            elif operation == "deactivate_user":
                external = adapter.deactivate_user(account.external_id)
            else:
                external = adapter.get_user(account.external_id)
            latency_ms = adapter.http.last_latency_ms
        except ConnectorError as error:
            breaker.record(connector, error)
            if audited:
                self._audit(
                    connector,
                    "connector.operation_run",
                    {
                        "operation": operation,
                        "employee_id": employee.id,
                        "error_category": error.category.value,
                        "error_code": error.code,
                    },
                    outcome=AuditOutcome.FAILURE,
                )
                self.session.commit()
            self._log(
                "connector operation failed",
                connector,
                operation=operation,
                employee_id=str(employee.id),
                category=error.category.value,
            )
            raise BadGatewayError(
                f"{connector.name}: {error.message}", details=error.to_dict()
            ) from error
        finally:
            adapter.close()
        breaker.record(connector, None)
        if audited:  # committed with the account link by _save_account
            self._audit(
                connector,
                "connector.operation_run",
                {"operation": operation, "employee_id": employee.id},
            )

        account = self._save_account(
            connector, employee, account, external.external_id, external.active, operation
        )
        self._log(
            "connector operation succeeded",
            connector,
            operation=operation,
            employee_id=str(employee.id),
            latency_ms=latency_ms,
        )
        return OperationResult(
            operation=operation,
            connector_id=connector.id,
            employee_id=employee.id,
            external_id=external.external_id,
            external_active=external.active,
            account_status=account.status,
            latency_ms=latency_ms,
        )

    def read_external_user(self, connector: Connector, external_id: str) -> ExternalUser:
        """Read one account from the application (reconciliation). Goes through the
        circuit breaker like every call; raises ConnectorError on failure."""
        adapter = self._adapter(connector, for_operation=True)
        breaker = CircuitBreaker(self.session, self.settings)
        try:
            breaker.before_call(connector)
            try:
                user = adapter.get_user(external_id)
            except ConnectorError as error:
                breaker.record(connector, error)
                raise
            breaker.record(connector, None)
            return user
        finally:
            adapter.close()

    def _save_account(
        self,
        connector: Connector,
        employee: Employee,
        account: ExternalAccount | None,
        external_id: str,
        external_active: bool,
        operation: str,
    ) -> ExternalAccount:
        now = datetime.now(UTC)
        if account is None:
            account = ExternalAccount(
                organization_id=connector.organization_id,
                connector_id=connector.id,
                employee_id=employee.id,
                external_id=external_id,
            )
            try:
                self.accounts.add(account)
            except IntegrityError as exc:  # a concurrent create_user linked it first
                self.session.rollback()
                raise ConflictError(
                    "This employee was linked by a concurrent request.", code="already_linked"
                ) from exc
        if operation != "get_user" or account.last_synced_at is None:
            account.last_synced_at = now
        account.status = (
            ExternalAccountStatus.ACTIVE if external_active else ExternalAccountStatus.DEACTIVATED
        )
        self.session.commit()
        return account

    # ---- helpers -----------------------------------------------------------------

    @staticmethod
    def _spec(connector_type: str) -> ConnectorSpec:
        cls = registry.get_connector_class(connector_type)
        if cls is None:
            raise UnprocessableError(
                f"Unknown connector type '{connector_type}'.",
                code="unknown_connector_type",
                details={"available": [s.connector_type for s in registry.catalog()]},
            )
        return cls.spec

    def _validate(
        self, spec: ConnectorSpec, config: dict[str, Any], credentials: dict[str, Any] | None
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        try:
            registry.validate_settings(spec, config, credentials)
        except registry.ConnectorConfigurationError as exc:
            raise UnprocessableError(
                f"Invalid connector {exc.field}.",
                code="invalid_connector_settings",
                details=exc.errors,
            ) from exc
        parsed_config = spec.config_model.model_validate(config)
        if parsed_config.base_url is not None:
            try:
                check_allowed_url(
                    str(parsed_config.base_url), self.settings.connector_allowed_hosts
                )
            except ConnectorError as exc:
                raise UnprocessableError(exc.message, code=exc.code) from exc
        normalized = parsed_config.model_dump(mode="json", exclude_none=True)
        if credentials is None:
            return normalized, None
        return normalized, _revealed(spec.credentials_model.model_validate(credentials))

    def _store_credentials(
        self, connector: Connector, spec: ConnectorSpec, secrets: dict[str, Any]
    ) -> None:
        encrypted = CredentialCipher.from_settings(self.settings).encrypt(secrets)
        hint = fingerprint(str(secrets.get(spec.fingerprint_field, "")))
        if connector.credential is None:
            connector.credential = ConnectorCredential(
                organization_id=connector.organization_id,
                connector_id=connector.id,
                auth_type=spec.auth_type,
                encrypted_secret=encrypted,
                fingerprint=hint,
            )
        else:  # rotation: replace in place, keep the row
            connector.credential.auth_type = spec.auth_type
            connector.credential.encrypted_secret = encrypted
            connector.credential.fingerprint = hint
        self.session.flush()

    @staticmethod
    def _ensure_connected(connector: Connector) -> None:
        if connector.status is ConnectorStatus.DISCONNECTED or connector.credential is None:
            raise ConflictError(
                "Connector is disconnected. Add credentials to reconnect it.",
                code="connector_disconnected",
            )

    def _adapter(self, connector: Connector, *, for_operation: bool = False) -> ConnectorAdapter:
        """Decrypt credentials and build the adapter.

        A configuration problem (unsupported version, host no longer allowed) is a failed
        connection test, but a 409 for an operation: there is nothing to retry.
        """
        self._ensure_connected(connector)
        secrets = CredentialCipher.from_settings(self.settings).decrypt(
            connector.credential.encrypted_secret
        )
        try:
            return registry.build_connector(
                connector.connector_type,
                version=connector.connector_version,
                config=connector.config,
                credentials=secrets,
                settings=self.settings,
            )
        except ConnectorError as error:
            if for_operation:
                raise ConflictError(error.message, code=error.code) from error
            raise

    def _audit(
        self,
        connector: Connector,
        action: str,
        details: dict[str, Any],
        *,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
    ) -> None:
        audit.record(
            self.session,
            organization_id=connector.organization_id,
            action=action,
            resource_type="connector",
            resource_id=connector.id,
            outcome=outcome,
            details=details,
        )

    @staticmethod
    def _log(message: str, connector: Connector, **fields: Any) -> None:
        # IDs, types and outcomes only - never config values, credentials or payloads.
        logger.info(
            message,
            extra={
                "organization_id": str(connector.organization_id),
                "connector_id": str(connector.id),
                "connector_type": connector.connector_type,
                **fields,
            },
        )
