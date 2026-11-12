"""Slack adapter - user provisioning through Slack's SCIM v2 API.

SIMULATED by default: the request shapes follow Slack's SCIM API (users with the core
and enterprise schemas, PATCH with replace operations, DELETE to deactivate), but this
adapter has only been verified against the local mock in mock-services/. Using it with
real Slack requires an Enterprise Grid / Business+ workspace, a SCIM-enabled token with
the `admin` scope, and SLACK_BASE_URL=https://api.slack.com (added to
CONNECTOR_ALLOWED_HOSTS).
"""

import re
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

SCIM_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"


class SlackConfig(BaseConnectorConfig):
    pass


class SlackCredentials(BaseCredentials):
    token: SecretStr = Field(min_length=8, description="SCIM API token (xoxp-...).")


def _user_name(email: str) -> str:
    """Slack handles: lowercase letters, digits, '.', '-', '_' (taken from the email)."""
    return re.sub(r"[^a-z0-9._-]", "", email.split("@", 1)[0].lower())[:21] or "user"


@register
class SlackConnector(Connector):
    spec: ClassVar[ConnectorSpec] = ConnectorSpec(
        connector_type="slack",
        display_name="Slack",
        version="1.0.0",
        description="Create, update and deactivate Slack users through the SCIM v2 API.",
        auth_type="bearer_token",
        simulated=True,
        config_model=SlackConfig,
        credentials_model=SlackCredentials,
        default_base_url_setting="slack_base_url",
        fingerprint_field="token",
    )
    credentials: SlackCredentials

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.credentials.token.get_secret_value()}"}

    def _attributes(self, profile: UserProfile) -> dict[str, Any]:
        return {
            "userName": _user_name(profile.email),
            "name": {"givenName": profile.first_name, "familyName": profile.last_name},
            "emails": [{"value": profile.email, "primary": True}],
            "title": profile.designation,
            SCIM_ENTERPRISE: {
                "employeeNumber": profile.employee_number,
                "department": profile.department,
            },
        }

    @staticmethod
    def _to_external(body: dict[str, Any]) -> ExternalUser:
        emails = body.get("emails") or []
        primary = next((e for e in emails if e.get("primary")), emails[0] if emails else {})
        name = body.get("name") or {}
        return ExternalUser(
            external_id=str(body["id"]),
            email=primary.get("value", ""),
            first_name=name.get("givenName", ""),
            last_name=name.get("familyName", ""),
            active=bool(body.get("active", True)),
            raw=body,
        )

    def test_connection(self) -> ConnectionCheck:
        self.http.request("GET", "/scim/v2/ServiceProviderConfig", headers=self._headers())
        return ConnectionCheck(
            ok=True, latency_ms=self.http.last_latency_ms, detail="SCIM API reachable."
        )

    def create_user(
        self, profile: UserProfile, *, idempotency_key: str | None = None
    ) -> ExternalUser:
        body = {
            "schemas": [SCIM_USER, SCIM_ENTERPRISE],
            "active": profile.active,
            **self._attributes(profile),
        }
        headers = {**self._headers(), **idempotency_headers(idempotency_key)}
        response = self.http.request("POST", "/scim/v2/Users", json=body, headers=headers)
        return self._to_external(response.json())

    def update_user(self, external_id: str, profile: UserProfile) -> ExternalUser:
        patch = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": self._attributes(profile)}],
        }
        response = self.http.request(
            "PATCH", f"/scim/v2/Users/{external_id}", json=patch, headers=self._headers()
        )
        return self._to_external(response.json())

    def deactivate_user(self, external_id: str) -> ExternalUser:
        # Slack's SCIM DELETE deactivates the user (history is kept); it returns no body.
        self.http.request("DELETE", f"/scim/v2/Users/{external_id}", headers=self._headers())
        return self.get_user(external_id)

    def get_user(self, external_id: str) -> ExternalUser:
        response = self.http.request(
            "GET", f"/scim/v2/Users/{external_id}", headers=self._headers()
        )
        return self._to_external(response.json())
