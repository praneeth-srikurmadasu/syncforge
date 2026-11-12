# 10 - Connector Framework

> **Scope:** implemented in Phase 4. Automatic execution from workflows is Phase 5;
> retries, idempotency keys and the circuit breaker are Phase 6. Nothing here is planned-only.

A **connector** is a configured connection from one organization to one external
application. The framework gives every application the same five operations and the same
error vocabulary, so the rest of SyncForge never needs to know which application it is
talking to.

## 1. What is real and what is simulated

| Connector | Follows the shape of | Verified against | Status |
|---|---|---|---|
| Slack (`slack` 1.0.0) | Slack SCIM v2 API: core + enterprise user schema, PATCH replace, DELETE deactivates | Local mock only | **Simulated** |
| Google Workspace (`google_workspace` 1.0.0) | Admin SDK Directory API `users` (insert, get, patch, `suspended`) | Local mock only | **Simulated** |
| Payroll (`payroll` 1.0.0) | A generic REST payroll API (no industry standard exists) | Local mock only | **Simulated** |

Every connector type reports `"simulated": true` in the API. None has been tested
against a real Slack or Google tenant. To use the real services you need:
- **Slack:** a SCIM-enabled plan (Business+ or Enterprise Grid) and a SCIM token.
  Set `SLACK_BASE_URL=https://api.slack.com` and add `api.slack.com` to
  `CONNECTOR_ALLOWED_HOSTS`.
- **Google:** a Workspace tenant and a service account with domain-wide delegation. The
  adapter's token exchange must switch from the mock's client-credentials grant to the
  JWT-bearer grant that Google uses (see section 6). Set the base URLs and allowed hosts
  to Google's endpoints.

## 2. Architecture

```mermaid
classDiagram
    class Connector {
        <<abstract>>
        +spec: ConnectorSpec
        +test_connection() ConnectionCheck
        +create_user(profile) ExternalUser
        +update_user(external_id, profile) ExternalUser
        +deactivate_user(external_id) ExternalUser
        +get_user(external_id) ExternalUser
    }
    class ConnectorSpec {
        connector_type
        version
        auth_type
        simulated
        config_model
        credentials_model
    }
    class ConnectorHttpClient {
        timeouts
        host allowlist
        no redirects
        +request() Response
    }
    class SlackConnector
    class GoogleWorkspaceConnector
    class PayrollConnector
    class Registry {
        +register(cls)
        +catalog()
        +build_connector(type, version, config, credentials)
    }
    Connector <|-- SlackConnector
    Connector <|-- GoogleWorkspaceConnector
    Connector <|-- PayrollConnector
    Connector --> ConnectorSpec
    Connector --> ConnectorHttpClient
    Registry ..> Connector : builds
```

| Module | Responsibility |
|---|---|
| `connectors/base.py` | The interface (`Connector`), `UserProfile` (what we send), `ExternalUser` (what comes back), `ConnectorSpec` (metadata) |
| `connectors/registry.py` | Adapters register by type; `build_connector` validates config and credentials, checks the version, and wires the HTTP client |
| `connectors/http.py` | The single outbound HTTP client (section 5) |
| `connectors/errors.py` | Error normalization (section 4) |
| `connectors/slack.py`, `google_workspace.py`, `payroll.py` | One adapter per application: request mapping and authentication only |
| `services/connectors.py` | Use cases: configure, test, disconnect, run operations; encryption; external-account links |
| `security/encryption.py` | Credential encryption at rest (section 7) |

**Why adapters ([ADR-0008](adr/0008-connector-adapter-pattern.md)):** the workflow engine
in Phase 5 will call `connector.create_user(profile)` without knowing the vendor.
Business rules live once, in the service:
- who may run what;
- tenant checks;
- "no account for terminated employees";
- account links.

Adapters only translate requests. To add an application you add an adapter; nothing else
changes.

## 3. The common interface

| Operation | Purpose | Slack | Google | Payroll |
|---|---|---|---|---|
| `test_connection` | Cheap read-only call proving the credentials work | `GET /scim/v2/ServiceProviderConfig` | token exchange + `GET /users?maxResults=1` | `GET /v1/ping` |
| `create_user` | Provision an account | `POST /scim/v2/Users` | `POST /admin/directory/v1/users` | `POST /v1/employees` |
| `update_user` | Push changed attributes | `PATCH` (SCIM replace) | `PATCH /users/{id}` | `PATCH /v1/employees/{id}` |
| `deactivate_user` | Revoke access, keep history | `DELETE` (Slack deactivates) | `PATCH {"suspended": true}` | `PATCH {"status": "inactive"}` |
| `get_user` | Read the account's current state | `GET /scim/v2/Users/{id}` | `GET /users/{id}` | `GET /v1/employees/{id}` |

The input is a `UserProfile` built from the employee: employee number, email, names,
department name, designation, location and active flag. `repr()` of profiles and external
users shows IDs only, so personal data cannot leak into logs or tracebacks.

**External accounts.** The ID an application assigns (Slack `U...`, Google numeric ID,
payroll `PR-...`) is stored in `external_accounts`, keyed by (connector, employee).
Updates and deactivations use that stored ID. Email is not a stable key, because people
change emails.

## 4. Error normalization

Every failure becomes a `ConnectorError` with a **category**. The category decides whether
a retry can help (the Phase 6 retry engine reads `retryable`):

| Category | Produced by | Retryable |
|---|---|---|
| `authentication` | 401; OAuth token request rejected | no |
| `authorization` | 403 | no |
| `validation` | 400, 422 | no |
| `not_found` | 404 | no |
| `conflict` | 409 (e.g. user already exists) | no |
| `rate_limited` | 429, with `retry_after` parsed from `Retry-After` (seconds or HTTP date, capped at 1 hour) | **yes** |
| `timeout` | connect or read timeout, 408 | **yes** |
| `network` | connection refused, DNS failure, reset | **yes** |
| `server` | 5xx (503 also reads `Retry-After`) | **yes** |
| `permanent` | any other 4xx, unexpected redirect | no |
| `configuration` | our side: disallowed host, unsupported version, bad stored settings | no |

The error message is taken from the vendor's own error format and truncated to 300
characters. Examples are SCIM `detail`, Google `error.message` and payroll
`error.message`. Credentials never appear in it, and the tests assert this for every
connector.

Through the API, a failed operation returns **`502 connector_error`**, with the
normalized error in `details`:

```json
{"error": {"code": "connector_error", "message": "slack: Simulated failure (503).",
  "details": {"category": "server", "code": "http_503", "status_code": 503,
              "retryable": true, "retry_after": null, "message": "Simulated failure (503)."},
  "request_id": "..."}}
```

A 429 from Slack is reported as `502` with `category: rate_limited`, not as our own 429:
SyncForge itself is not rate-limiting the caller. **Phase 4 classifies and reports**
rate limits and transient failures. Acting on them with backoff, jitter, `Retry-After`
scheduling and dead-lettering is Phase 6.

## 5. The HTTP client (`ConnectorHttpClient`)

Every adapter makes its calls through one client:

| Protection | Detail |
|---|---|
| Timeouts | `CONNECTOR_CONNECT_TIMEOUT_SECONDS` (default 3) and `CONNECTOR_READ_TIMEOUT_SECONDS` (default 10). No call can hang a request or worker forever. |
| Host allowlist (SSRF) | The base URL's host must be in `CONNECTOR_ALLOWED_HOSTS`. Checked when a connector is saved *and* on every call. Without it, an admin could point a connector at an internal address such as the cloud metadata service `169.254.169.254`. |
| No redirects | A redirect could lead to a host that isn't allowed, so it is treated as a permanent error. |
| No implicit proxies | `trust_env=False`: environment proxy settings are ignored. |
| No credentials in URLs | `http://user:pass@host` is rejected. |
| Latency | Every call records `last_latency_ms`, which connection tests and operations return. |
| No body logging | Request and response bodies and headers are never logged. |

The default endpoints of the mocks use `127.0.0.1`, not `localhost`. On Windows,
`localhost` resolves to IPv6 `::1` first; nothing listens there, and Windows retries a refused
loopback connection for about 2 seconds before trying IPv4, so every call would be ~2 s slow.

Known limitation: the allowlist matches **host names**, not resolved IP addresses, so a
DNS name that resolves to an internal IP would be allowed. Production should list only
vendor host names and restrict egress at the network level.

## 6. Authentication styles and the OAuth lifecycle

| Connector | `auth_type` | Credentials (encrypted) |
|---|---|---|
| Slack | `bearer_token` | `token` |
| Google Workspace | `oauth2_client_credentials` | `client_id`, `client_secret` |
| Payroll | `api_key` | `api_key` |

Google shows a full OAuth 2.0 token lifecycle:

```mermaid
sequenceDiagram
    participant S as ConnectorService
    participant G as GoogleWorkspaceConnector
    participant C as Token cache (process memory)
    participant T as POST /oauth2/token
    participant A as Directory API

    S->>G: create_user(profile)
    G->>C: token for (base_url, client_id, sha256(secret))?
    alt no token, or expires within 60 s
        G->>T: grant_type=client_credentials, client_id, client_secret
        T-->>G: access_token, expires_in
        G->>C: store until expiry
    end
    G->>A: POST /users  (Bearer token)
    alt 401 - token revoked or expired early
        A-->>G: 401
        G->>T: request a fresh token (once)
        G->>A: retry the call once
    end
    A-->>G: 200 user
    G-->>S: ExternalUser
```

- Tokens are cached per process. The key includes a hash of the secret, so rotating
  the secret never reuses a token issued for the old one.
- The 401 refresh happens **once**. If the fresh token is also rejected, the
  credentials themselves are wrong, so the error surfaces as `authentication`.
- A rejected token request (wrong client ID or secret) becomes `authentication` with code
  `oauth_invalid_client`.
- **Simplification:** the real Directory API uses the JWT-bearer grant with a service
  account and domain-wide delegation. The mock uses the client-credentials grant. The
  lifecycle (obtain, cache, expire, refresh) is the same; only `_fetch_token` would change.
- The full OAuth **authorization-code** flow, where a user clicks "Connect with Google"
  in a browser, is not implemented. It requires a registered OAuth app and redirect
  URIs, and is listed in future improvements.

## 7. Credential security

- Credentials are validated against the connector's credentials schema and encrypted with
  **Fernet** (AES-128-CBC with an HMAC-SHA256 signature) before they reach the database
  ([ADR-0009](adr/0009-encrypting-connector-credentials.md)). A tampered ciphertext fails
  to decrypt instead of returning garbage.
- They live in `connector_credentials`, separate from `connectors`, and are decrypted only
  at the moment an adapter is built for a call.
- **Never returned.** Responses show `auth_type` and a fingerprint (the last 4 characters,
  e.g. `...oken`) so admins can tell keys apart. Secrets shorter than 12 characters show
  `...****`.
- **Never logged.** Logs carry connector, organization and employee IDs and outcomes only.
  `test_logs_never_contain_credentials` checks every captured log record.
- **Never echoed.** Validation errors name the field (`credentials.token`), never the value.
- **Rotation:** `PATCH` with new credentials replaces the ciphertext in place and puts the
  connector back to `pending`.
- **Revocation:** `POST .../disconnect` deletes the credentials row. The connector can no
  longer be used until new credentials are supplied.
- **Key management:** `CONNECTOR_ENCRYPTION_KEY` holds one or more comma-separated Fernet
  keys. The first key encrypts and all keys decrypt, so a key can be rotated without
  downtime. Without a key, connectors cannot be created (`503 encryption_not_configured`),
  and production refuses to start.

## 8. Connector lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending : POST /connectors
    pending --> connected : test ok
    pending --> error : test failed
    connected --> error : test failed
    error --> connected : test ok
    connected --> pending : PATCH config/credentials
    error --> pending : PATCH config/credentials
    pending --> disconnected : disconnect
    connected --> disconnected : disconnect
    error --> disconnected : disconnect
    disconnected --> pending : PATCH credentials (reconnect)
```

The status reflects the **last connection test**. The time and normalized error of the
last test are stored on the connector (`last_tested_at`, `last_error_category`,
`last_error_message`). Operations are allowed in any state except `disconnected`, because
an operation is itself a live check.

## 9. Versioning

Each adapter declares a semantic version. A connector stores the version it was
configured with (`connectors.connector_version`). `build_connector` refuses to run a
connector whose **major** version differs from the installed adapter: a major bump means
the config or credentials schema changed incompatibly. The connector then reports
`connector_version_unsupported`, as a failed test or a `409` for operations, and must be
re-created. Minor and patch versions are compatible by definition.

## 10. Sequence: one operation

```mermaid
sequenceDiagram
    participant C as Client
    participant R as POST /connectors/{id}/operations
    participant S as ConnectorService
    participant DB as PostgreSQL
    participant A as Adapter
    participant X as External API

    C->>R: {"operation": "create_user", "employee_id": ...}
    R->>R: require_org_permission(connectors:manage)
    R->>S: run_operation
    S->>DB: load connector + employee (same organization) + existing link
    S->>S: rules: not disconnected, not already linked, not terminated
    S->>S: decrypt credentials, build adapter
    S->>A: create_user(profile)
    A->>X: HTTP (timeouts, allowlist)
    X-->>A: 201 {"id": "U..."}
    A-->>S: ExternalUser
    S->>DB: INSERT external_accounts, COMMIT
    S-->>C: 200 {external_id, external_active, account_status, latency_ms}
```

No row locks are held while the external call is in flight, so a slow vendor cannot block
other requests. If two requests create the same link at the same moment, the unique
constraint on `(connector_id, employee_id)` lets one win. The vendor itself rejects the
duplicate account.

**Phase 4 limitation:** operations are synchronous, triggered by an admin, and attempted
once. Suppose the vendor creates the account but SyncForge crashes before saving the
link. Retrying `create_user` then gets `conflict` from the vendor. Phase 6 resolves this
with idempotency keys and by adopting the existing account.

## 11. Adding a new connector

1. Create `backend/app/connectors/<name>.py`.
2. Define its config model (non-secret settings) and its credentials model
   (`SecretStr` for secrets).
3. Subclass `Connector` and set `spec` (type, version `1.0.0`, auth type, simulated flag,
   models, default base-URL setting, fingerprint field).
4. Implement the five operations by mapping `UserProfile` to the vendor's API. Use
   `self.http.request(...)`; never create your own HTTP client.
5. Decorate the class with `@register` and import the module in
   `app/connectors/__init__.py`.
6. Add the default base URL to `Settings` and `.env.example`.
7. Add a mock to `mock-services/` and add the type to the parametrized adapter tests.

The service, API, encryption, error handling, permissions and tenant isolation need no
changes.

## 12. Mock services and failure injection

See [mock-services/README.md](../mock-services/README.md). Each mock supports queued faults:
- a status code (e.g. 503);
- a rate limit with `Retry-After`;
- a timeout delay.

The Google mock can also expire every issued token. The connector tests start all three
mocks as real HTTP servers, so every failure category above is produced over real sockets.

## 13. Tests

| File | Covers |
|---|---|
| `test_connector_core.py` | Status-to-category mapping, `Retry-After` parsing, transport errors, redirect refusal, host allowlist, registry, versioning, field-only validation errors |
| `test_encryption.py` | Round trip, tamper detection, wrong key, key rotation, blank or missing key, production requirement, fingerprints |
| `test_connector_models.py` | Unique names, one credential set per connector, cross-organization rejection, cascades, external-account uniqueness |
| `test_connector_adapters.py` | Each of the 3 adapters against its live mock: test, full lifecycle, payload shape, wrong credentials, conflict, not found, 503, 429 with `Retry-After`, read timeout, refused connection, Google token caching and refresh |
| `test_connectors_api.py` | Catalog, create with encrypted storage, validation, test success and failure, rotation, disconnect and reconnect, operations for all 3 types, 502 mapping, permissions, tenant isolation, no credentials in logs |

### Platform note: refused connections on Windows

On Linux a connection to a closed local port is refused immediately (a `network` error). On
Windows it is retried for about 2 seconds first, so with a 1-second connect timeout the same
situation surfaces as `timeout` / `connect_timeout`. Both are classified correctly and both are
retryable. `test_unreachable_service_is_a_network_error` uses a 5-second connect timeout so it
asserts `network` on every OS. Found when the suite first ran on Windows (it had only run on
Linux before).
