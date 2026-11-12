"""Google Workspace adapter - users through the Admin SDK Directory API.

SIMULATED by default: request shapes follow the Directory API `users` resource (insert,
get, patch, `suspended` for deactivation), verified only against the local mock.

Authentication is OAuth 2.0. The adapter exchanges the client ID and secret for a
short-lived access token at `{base_url}/oauth2/token`, caches it in memory until shortly
before it expires, and - if the API still rejects it (revoked, expired early) - discards
it and retries the call once with a fresh token. The real Directory API uses a service
account with the JWT-bearer grant and domain-wide delegation; the mock uses the
client-credentials grant, which exercises the same token lifecycle. Moving to real
Google means replacing `_fetch_token` with the JWT-bearer exchange.
"""

import hashlib
import threading
import time
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
from app.connectors.errors import ConnectorError, ErrorCategory
from app.connectors.registry import register

# Refresh a cached token this many seconds before it expires.
_EXPIRY_MARGIN_SECONDS = 60

# (base_url, client_id, sha256(secret)) -> (access_token, expires_at). Process-local.
_token_cache: dict[tuple[str, str, str], tuple[str, float]] = {}
_token_lock = threading.Lock()


def clear_token_cache() -> None:
    with _token_lock:
        _token_cache.clear()


class GoogleWorkspaceConfig(BaseConnectorConfig):
    customer: str = Field(
        default="my_customer", max_length=100, description="Directory customer ID."
    )


class GoogleWorkspaceCredentials(BaseCredentials):
    client_id: str = Field(min_length=3, max_length=200)
    client_secret: SecretStr = Field(min_length=8)


@register
class GoogleWorkspaceConnector(Connector):
    spec: ClassVar[ConnectorSpec] = ConnectorSpec(
        connector_type="google_workspace",
        display_name="Google Workspace",
        version="1.0.0",
        description="Create, update and suspend Google Workspace accounts (Directory API).",
        auth_type="oauth2_client_credentials",
        simulated=True,
        config_model=GoogleWorkspaceConfig,
        credentials_model=GoogleWorkspaceCredentials,
        default_base_url_setting="google_workspace_base_url",
        fingerprint_field="client_secret",
    )
    config: GoogleWorkspaceConfig
    credentials: GoogleWorkspaceCredentials

    # ---- OAuth token lifecycle ---------------------------------------------------

    def _cache_key(self) -> tuple[str, str, str]:
        secret = self.credentials.client_secret.get_secret_value().encode()
        return (self.http.base_url, self.credentials.client_id, hashlib.sha256(secret).hexdigest())

    def _fetch_token(self) -> tuple[str, float]:
        try:
            response = self.http.request(
                "POST",
                "/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.credentials.client_id,
                    "client_secret": self.credentials.client_secret.get_secret_value(),
                },
            )
        except ConnectorError as exc:
            if exc.category in (ErrorCategory.AUTHENTICATION, ErrorCategory.VALIDATION):
                raise ConnectorError(
                    ErrorCategory.AUTHENTICATION,
                    "OAuth token request was rejected: check the client ID and secret.",
                    "oauth_invalid_client",
                    status_code=exc.status_code,
                ) from exc
            raise
        body = response.json()
        expires_in = float(body.get("expires_in", 3600))
        return body["access_token"], time.time() + expires_in

    def _access_token(self, *, refresh: bool = False) -> str:
        key = self._cache_key()
        with _token_lock:
            cached = _token_cache.get(key)
        if cached and not refresh and cached[1] - _EXPIRY_MARGIN_SECONDS > time.time():
            return cached[0]
        token, expires_at = self._fetch_token()
        with _token_lock:
            _token_cache[key] = (token, expires_at)
        return token

    def _call(
        self, method: str, path: str, *, extra_headers: dict[str, str] | None = None, **kwargs: Any
    ) -> Any:
        """Call the API; on 401, get a fresh token and retry exactly once."""
        for attempt in (1, 2):
            headers = {
                "Authorization": f"Bearer {self._access_token(refresh=attempt == 2)}",
                **(extra_headers or {}),
            }
            try:
                return self.http.request(method, path, headers=headers, **kwargs)
            except ConnectorError as exc:
                if exc.category is not ErrorCategory.AUTHENTICATION or attempt == 2:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    # ---- mapping -----------------------------------------------------------------

    @staticmethod
    def _attributes(profile: UserProfile) -> dict[str, Any]:
        return {
            "primaryEmail": profile.email,
            "name": {"givenName": profile.first_name, "familyName": profile.last_name},
            "organizations": [
                {"title": profile.designation, "department": profile.department, "primary": True}
            ],
            "locations": [{"type": "desk", "area": profile.location}] if profile.location else [],
            "externalIds": [{"type": "organization", "value": profile.employee_number}],
        }

    @staticmethod
    def _to_external(body: dict[str, Any]) -> ExternalUser:
        name = body.get("name") or {}
        organizations = body.get("organizations") or []
        organization = next(
            (o for o in organizations if o.get("primary")),
            organizations[0] if organizations else {},
        )
        locations = body.get("locations") or []
        return ExternalUser(
            external_id=str(body["id"]),
            email=body.get("primaryEmail", ""),
            first_name=name.get("givenName", ""),
            last_name=name.get("familyName", ""),
            active=not body.get("suspended", False),
            department=organization.get("department"),
            designation=organization.get("title"),
            location=locations[0].get("area") if locations else None,
            raw=body,
        )

    # ---- operations --------------------------------------------------------------

    def test_connection(self) -> ConnectionCheck:
        self._call(
            "GET",
            "/admin/directory/v1/users",
            params={"customer": self.config.customer, "maxResults": 1},
        )
        return ConnectionCheck(
            ok=True,
            latency_ms=self.http.last_latency_ms,
            detail="OAuth token issued; Directory API reachable.",
        )

    def create_user(
        self, profile: UserProfile, *, idempotency_key: str | None = None
    ) -> ExternalUser:
        body = {**self._attributes(profile), "suspended": not profile.active}
        response = self._call(
            "POST",
            "/admin/directory/v1/users",
            json=body,
            extra_headers=idempotency_headers(idempotency_key),
        )
        return self._to_external(response.json())

    def update_user(self, external_id: str, profile: UserProfile) -> ExternalUser:
        response = self._call(
            "PATCH", f"/admin/directory/v1/users/{external_id}", json=self._attributes(profile)
        )
        return self._to_external(response.json())

    def deactivate_user(self, external_id: str) -> ExternalUser:
        response = self._call(
            "PATCH", f"/admin/directory/v1/users/{external_id}", json={"suspended": True}
        )
        return self._to_external(response.json())

    def get_user(self, external_id: str) -> ExternalUser:
        return self._to_external(
            self._call("GET", f"/admin/directory/v1/users/{external_id}").json()
        )
