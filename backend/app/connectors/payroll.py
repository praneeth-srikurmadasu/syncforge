"""Payroll adapter - a generic REST payroll API.

SIMULATED: there is no single "payroll API" standard, so this adapter targets the
local mock in mock-services/ (API-key authentication, JSON employee records). It shows
how a third authentication style plugs into the same connector interface.
"""

from typing import Any, ClassVar

from pydantic import Field, SecretStr

from app.connectors.base import (
    BaseConnectorConfig,
    BaseCredentials,
    ConnectionCheck,
    Connector,
    ConnectorSpec,
    ExternalUser,
    UserProfile,
    idempotency_headers,
)
from app.connectors.registry import register


class PayrollConfig(BaseConnectorConfig):
    pass


class PayrollCredentials(BaseCredentials):
    api_key: SecretStr = Field(min_length=8)


@register
class PayrollConnector(Connector):
    spec: ClassVar[ConnectorSpec] = ConnectorSpec(
        connector_type="payroll",
        display_name="Payroll (mock)",
        version="1.0.0",
        description="Create, update and end payroll records in a REST payroll system.",
        auth_type="api_key",
        simulated=True,
        config_model=PayrollConfig,
        credentials_model=PayrollCredentials,
        default_base_url_setting="payroll_base_url",
        fingerprint_field="api_key",
    )
    credentials: PayrollCredentials

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.credentials.api_key.get_secret_value()}

    @staticmethod
    def _attributes(profile: UserProfile) -> dict[str, Any]:
        return {
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "email": profile.email,
            "department": profile.department,
            "designation": profile.designation,
            "location": profile.location,
        }

    @staticmethod
    def _to_external(body: dict[str, Any]) -> ExternalUser:
        return ExternalUser(
            external_id=str(body["id"]),
            email=body.get("email", ""),
            first_name=body.get("first_name", ""),
            last_name=body.get("last_name", ""),
            active=body.get("status") == "active",
            department=body.get("department"),
            designation=body.get("designation"),
            location=body.get("location"),
            raw=body,
        )

    def test_connection(self) -> ConnectionCheck:
        self.http.request("GET", "/v1/ping", headers=self._headers())
        return ConnectionCheck(
            ok=True, latency_ms=self.http.last_latency_ms, detail="Payroll API reachable."
        )

    def create_user(
        self, profile: UserProfile, *, idempotency_key: str | None = None
    ) -> ExternalUser:
        body = {
            "employee_number": profile.employee_number,
            "status": "active" if profile.active else "inactive",
            **self._attributes(profile),
        }
        headers = {**self._headers(), **idempotency_headers(idempotency_key)}
        response = self.http.request("POST", "/v1/employees", json=body, headers=headers)
        return self._to_external(response.json())

    def update_user(self, external_id: str, profile: UserProfile) -> ExternalUser:
        response = self.http.request(
            "PATCH",
            f"/v1/employees/{external_id}",
            json=self._attributes(profile),
            headers=self._headers(),
        )
        return self._to_external(response.json())

    def deactivate_user(self, external_id: str) -> ExternalUser:
        response = self.http.request(
            "PATCH",
            f"/v1/employees/{external_id}",
            json={"status": "inactive"},
            headers=self._headers(),
        )
        return self._to_external(response.json())

    def get_user(self, external_id: str) -> ExternalUser:
        response = self.http.request("GET", f"/v1/employees/{external_id}", headers=self._headers())
        return self._to_external(response.json())
