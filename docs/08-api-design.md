# 08 - API Design

> **Scope:** endpoints implemented as of Phase 5. Live, always-current reference:
> **http://127.0.0.1:8000/docs** (Swagger UI) and `/openapi.json`, generated from the code.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | Business APIs live under `/api/v1`. Probes (`/health`, `/ready`) are unversioned. |
| Format | JSON request and response bodies; UTF-8. |
| IDs | UUID strings. |
| Timestamps | ISO 8601 in UTC, e.g. `2026-11-11T12:41:04.146404Z`. |
| Authentication | `Authorization: Bearer <access_token>` from `POST /api/v1/auth/login`. |
| Request tracing | Every response has `X-Request-ID`; send your own (`[A-Za-z0-9._-]{1,128}`) to correlate. |
| Errors | Always `{"error": {"code", "message", "details", "request_id"}}`. Branch on `code`, not `message`. |
| Validation | `422 validation_error`; `details` is a list of `{field, message, type}`. Input values are never echoed back. |
| Pagination | List endpoints take `limit` (1-100) and `offset` (default 0) and return `{"items", "total", "limit", "offset"}`. Every sort ends with `id` as a tie-breaker, so pages never overlap or skip rows. |
| Partial updates | `PATCH` changes only the fields present in the body. Sending `null` clears an optional field; unknown fields are rejected (`422`). |
| Tenant isolation | Any resource under `/organizations/{organization_id}` returns **404** to non-members, and **403** to members whose role lacks the permission. |
| Idempotency | `POST .../employees` accepts an optional `Idempotency-Key` header; a repeat returns the stored response with `Idempotent-Replayed: true` ([docs/13](13-idempotency.md)). |
| Optimistic concurrency | Employee responses carry `ETag: "<version>"`; `PATCH`, terminate and archive accept `If-Match` and answer `412 version_conflict` if the employee changed since ([docs/14](14-data-integrity.md#3-optimistic-concurrency-on-employees)). |
| Audit | Every change listed in [docs/14](14-data-integrity.md#2-the-audit-log) writes an audit entry in the same transaction. |

### Error codes in use

| HTTP | `code` | Meaning |
|---|---|---|
| 401 | `not_authenticated` | No bearer token sent (or a non-Bearer scheme) |
| 401 | `invalid_token` | Malformed, wrongly signed, wrong issuer/audience/type, or user missing/inactive |
| 401 | `token_expired` | Token past its `exp` |
| 401 | `token_revoked` | Token was logged out |
| 401 | `invalid_credentials` | Login failed (same message for every cause) |
| 403 | `superadmin_required` | Platform endpoint (security events) called by someone who is not a Super Admin |
| 403 | `insufficient_role` | Member of the organization, but the role lacks the permission; `details.required_permission` names it |
| 404 | `not_found` | Unknown route |
| 404 | `organization_not_found` | Organization does not exist, is deactivated, or the caller is not a member |
| 404 | `user_not_found` | Adding a member: no active user has that email |
| 404 | `member_not_found` | The user is not a member of this organization |
| 405 | `method_not_allowed` | Wrong HTTP method |
| 413 | `payload_too_large` | Request body over `MAX_REQUEST_BODY_BYTES` (default 1 MiB); refused before the handler runs |
| 429 | `rate_limited` | Too many sign-in or registration attempts; `Retry-After` header and `details.retry_after_seconds` say how long to wait |
| 409 | `email_taken` | Registration with an existing email (case-insensitive) |
| 409 | `slug_taken` | Organization slug already in use |
| 409 | `already_member` | User is already a member of the organization |
| 409 | `last_admin` | Change would leave the organization with no Organization Admin |
| 404 | `department_not_found` | Department does not exist in this organization (department endpoints) |
| 404 | `employee_not_found` | Employee does not exist in this organization (also for another organization's employee ID) |
| 409 | `department_name_taken` | Department name already used in this organization (case-insensitive) |
| 409 | `department_in_use` | Department still has employees; `details.employee_count` |
| 409 | `employee_number_taken` | Employee number already used in this organization |
| 409 | `email_taken` | (employees) Email already used by another employee in this organization |
| 409 | `employee_terminated` | Employee is terminated: cannot be modified or terminated again |
| 409 | `employee_not_terminated` | Only terminated employees can be archived |
| 422 | `validation_error` | Request body or query failed validation |
| 422 | `department_not_found` | (employee body) `department_id` unknown in this organization |
| 422 | `manager_not_found` | `manager_id` unknown in this organization |
| 422 | `manager_terminated` | The chosen manager is terminated |
| 422 | `manager_cycle` | The change would make someone their own (direct or indirect) manager |
| 422 | `termination_before_joining` | Termination date earlier than joining date |
| 422 | `invalid_date_range` | `joined_from` is after `joined_to` |
| 404 | `connector_not_found` | Connector does not exist in this organization |
| 409 | `connector_name_taken` | Connector name already used in this organization |
| 409 | `connector_disconnected` | Connector has no credentials (disconnected); supply credentials to reconnect |
| 409 | `connector_version_unsupported` | Stored connector was configured with an incompatible adapter major version |
| 409 | `already_linked` | `create_user`: the employee already has an account in this application |
| 409 | `not_linked` | `update_user` / `deactivate_user` / `get_user` before `create_user` |
| 409 | `employee_terminated` | (connectors) `create_user` for a terminated employee |
| 422 | `unknown_connector_type` | `connector_type` not in the catalog; `details.available` lists valid types |
| 422 | `invalid_connector_settings` | Config or credentials do not match the connector's schema; `details` names fields, never values |
| 422 | `invalid_base_url` / `host_not_allowed` | Base-URL override is not http(s), embeds credentials, or its host is not in `CONNECTOR_ALLOWED_HOSTS` |
| 422 | `employee_not_found` | (connector operations) employee unknown in this organization |
| 502 | `connector_error` | The external application failed; `details` is the normalized error (category, code, retryable, retry_after, status_code) |
| 503 | `encryption_not_configured` | `CONNECTOR_ENCRYPTION_KEY` is not set, so credentials cannot be stored |
| 404 | `workflow_not_found` | Workflow does not exist in this organization |
| 409 | `workflow_name_taken` | Workflow name already used in this organization |
| 409 | `connector_disconnected` | (workflow activation) a step uses a disconnected connector; `details.connectors` lists their names |
| 422 | `connector_not_found` | (workflow steps) connector unknown in this organization - also for another organization's connector; `details.ids` |
| 422 | `duplicate_step` | The same connector and operation appear more than once in a workflow |
| 404 | `event_not_found` | Integration event does not exist in this organization |
| 404 | `dead_letter_not_found` | Dead-letter entry does not exist in this organization |
| 409 | `already_replayed` | The dead-letter entry was already replayed; `details.replayed_at` |
| 409 | `workflow_inactive` | Replay refused: none of the failed workflows is active |
| 409 | `event_not_dead_lettered` | Replay refused: the event is not in the dead-letter state (invariant guard) |
| 422 | `idempotency_key_reused` | The `Idempotency-Key` was already used for a different request |
| 412 | `version_conflict` | `If-Match` was sent and the employee changed since; `details.expected_version`, `details.current_version` |
| 422 | `invalid_if_match` | `If-Match` is not an ETag returned by this API |
| 404 | `conflict_not_found` | Data conflict does not exist in this organization |
| 404 | `field_not_found` | Unknown field in a data-source policy |
| 409 | `conflict_not_open` | The conflict is already resolved or dismissed |
| 409 | `conflict_stale` | The employee changed since the conflict was detected; reconcile again |
| 409 | `connector_disconnected` | (reconcile) the connector has no credentials |
| 422 | `resolution_against_policy` | Chose the non-authoritative side without `override: true` and a note; `details.authoritative` |
| 422 | `note_required` | Dismissing, or deciding against the policy, without a note |
| 422 | `department_not_found` | (conflicts) adopting a department SyncForge does not have |
| 422 | `reactivation_not_supported` | Pushing "account active" to an application: the connectors cannot reactivate |
| 422 | `invalid_policy` | `connector_id` missing for `source: connector`, or given for `source: syncforge` |
| 500 | `internal_error` | Unexpected server error (details only in logs) |
| 503 | `not_ready` | Readiness check failed (database unreachable) |

All 401 responses include `WWW-Authenticate: Bearer`.

## 2. Probes

### `GET /health`
Auth: none. `200 {"status": "ok", "service": "syncforge-api", "version": "0.2.0"}`

### `GET /ready`
Auth: none. `200 {"status": "ready", "checks": {"database": "ok"}}`, or
`503` with `code: not_ready`, `details: {"database": "unreachable"}`.

## 3. Authentication - `/api/v1/auth`

### `POST /api/v1/auth/register`
Auth: none. Creates a platform user who belongs to no organization yet.

Request:
```json
{"email": "ada@acme.example", "password": "correct-horse-battery", "full_name": "Ada Lovelace"}
```

| Field | Rules |
|---|---|
| email | valid email; normalised to lowercase |
| password | 8-128 characters, any characters (no composition rules); refused if it is on the bundled list of common passwords, is one repeated character, contains "syncforge", or contains the email's name (4+ characters) |
| full_name | 1-200 characters after trimming whitespace |

`201`:
```json
{"id": "9728de53-...", "email": "ada@acme.example", "full_name": "Ada Lovelace",
 "is_active": true, "is_superadmin": false, "created_at": "2026-11-11T12:41:04.146404Z"}
```
Errors: `409 email_taken`, `422 validation_error` (a refused password is reported on the
`password` field with the reason, never the value), `429 rate_limited` (more than
`AUTH_REGISTER_IP_LIMIT` registrations from one client IP per `AUTH_REGISTER_IP_WINDOW_SECONDS`;
defaults 50 per hour).
Idempotency: not idempotent - a repeat returns `409`.

### `POST /api/v1/auth/login`
Auth: none.

Request: `{"email": "ada@acme.example", "password": "correct-horse-battery"}`

`200`: `{"access_token": "eyJ...", "token_type": "bearer", "expires_in": 1800}`

Errors: `401 invalid_credentials` - identical for unknown email, wrong password and
inactive account. `422 validation_error`. `429 rate_limited` with `Retry-After` when either
limit is reached:

| Limit | Counts | Default |
|---|---|---|
| Per client IP | every login attempt | 60 per 60 s |
| Per account (normalized email) | failed attempts, also for unknown emails | 10 per 15 min |

While the per-account limit is reached, even the correct password is refused, so guessing
cannot continue. Windows are fixed (aligned to the clock), so `Retry-After` is the time to
the end of the current window.

### `GET /api/v1/auth/me`
Auth: bearer token.

`200`: the user fields above plus
```json
"memberships": [{"organization_id": "...", "organization_name": "Acme Corp",
                 "organization_slug": "acme", "role": "integration_manager"}]
```
Errors: `401` (`not_authenticated`, `invalid_token`, `token_expired`, `token_revoked`).

### `POST /api/v1/auth/logout`
Auth: bearer token. Revokes **that token only**; other sessions of the same user keep working.

`204` (no body). A second call with the same token returns `401 token_revoked`.

### `GET /api/v1/auth/activity?limit=20`
Auth: bearer token. The caller's own security events, newest first (`limit` 1-100,
default 20): sign-ins, failed sign-ins (with `reason`: `wrong_password`, `inactive_user`),
sign-in refusals by the per-account limit, sign-outs and the account's creation.

`200`:
```json
[{"id": 812, "event": "login_succeeded", "reason": null, "client_ip": "203.0.113.24",
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; ...) Chrome/158.0 ...",
  "created_at": "2026-11-12T16:55:02.114Z"}]
```
Events whose account could not be tied to a user (an unknown email, a refusal by the
per-IP limit) are not in anyone's own history; Super Admins see them below.

## 3a. Platform security events - `/api/v1/security-events`

### `GET /api/v1/security-events`
Auth: bearer token of a **Super Admin** (others: `403 superadmin_required`). All security
events, newest first, paginated (`limit`, `offset`). Filters: `event`
(`login_succeeded`, `login_failed`, `login_rate_limited`, `logout`, `registered`,
`registration_rate_limited`), `user_id`, `client_ip`, `since`, `until`.

Items add `user_id`, `account_hash` (SHA-256 of the normalized email: groups attempts on
one account without storing what was typed) and `request_id` to the fields above.
A rate-limit refusal is recorded once per rule, subject and window (the first refused
attempt); repeats are in the logs (`rate limited`).

## 4. Organizations - `/api/v1/organizations`

Permissions required per endpoint (see [security design](15-security-design.md#9-authorization-model)
for the role matrix):

| Method and path | Permission | Notes |
|---|---|---|
| `POST /api/v1/organizations` | any authenticated user | Caller becomes the first `org_admin` |
| `GET /api/v1/organizations` | any authenticated user | Lists caller's active organizations; Super Admin sees all |
| `GET /api/v1/organizations/{organization_id}` | `org:read` | |
| `PATCH /api/v1/organizations/{organization_id}` | `org:update` | Body: `{"name": "..."}` |
| `GET /api/v1/organizations/{organization_id}/members` | `members:read` | Paginated |
| `POST /api/v1/organizations/{organization_id}/members` | `members:manage` | Body: `{"email", "role"}` - user must already be registered |
| `PATCH /api/v1/organizations/{organization_id}/members/{user_id}` | `members:manage` | Body: `{"role"}` |
| `DELETE /api/v1/organizations/{organization_id}/members/{user_id}` | `members:manage` | `204` |

### `POST /api/v1/organizations`

Request: `{"name": "Acme Corp", "slug": "acme"}` - `slug` is optional (lowercase letters,
digits, single hyphens, max 63). When omitted it is generated from the name
(`"Acme Corp"` -> `acme-corp`); if that is taken, a random suffix is added (`acme-corp-4f9a1c`).
An explicitly requested slug that is taken returns `409 slug_taken`.

`201`:
```json
{"id": "ff1c1444-...", "name": "Acme Corp", "slug": "acme-corp", "is_active": true,
 "created_at": "2026-11-11T13:01:03.841893Z", "my_role": "org_admin"}
```
`my_role` is the caller's role in that organization (`null` for a Super Admin who is not a member).

### `GET /api/v1/organizations?limit=20&offset=0`

`200`: `{"items": [<organization>, ...], "total": 1, "limit": 20, "offset": 0}`

### Members

`GET .../members` item:
```json
{"user_id": "96e94f5a-...", "email": "bob@acme.example", "full_name": "Bob",
 "role": "viewer", "joined_at": "2026-11-11T13:01:03.891217Z"}
```
Errors: `404 user_not_found`, `409 already_member` (add); `404 member_not_found`,
`409 last_admin` (change role / remove).

## 5. Departments - `/api/v1/organizations/{organization_id}/departments`

| Method and path | Permission | Notes |
|---|---|---|
| `GET .../departments?limit=50&offset=0` | `departments:read` | Sorted by name (case-insensitive); each item has `employee_count` |
| `POST .../departments` | `departments:manage` | Body `{"name": "Engineering"}` (1-100 chars, trimmed). `201`. `409 department_name_taken` |
| `PATCH .../departments/{department_id}` | `departments:manage` | Body `{"name": "..."}`. Changing only the letter case of its own name is allowed |
| `DELETE .../departments/{department_id}` | `departments:manage` | `204`, or `409 department_in_use` while any employee (including archived) references it |

Item: `{"id": "...", "name": "Engineering", "employee_count": 7, "created_at": "..."}`

## 6. Employees - `/api/v1/organizations/{organization_id}/employees`

| Method and path | Permission | Emits (lifecycle events) |
|---|---|---|
| `GET .../employees` | `employees:read` | - |
| `GET .../employees/{employee_id}` | `employees:read` | - |
| `POST .../employees` | `employees:write` | `employee.created` |
| `PATCH .../employees/{employee_id}` | `employees:write` | `employee.department_changed`, `employee.manager_changed`, `employee.updated` (as applicable) |
| `POST .../employees/{employee_id}/terminate` | `employees:write` | `employee.terminated`, plus `employee.manager_changed` per moved direct report |
| `DELETE .../employees/{employee_id}` | `employees:write` | - (archive, see below) |

Routes are nested under the organization (rather than the `/api/v1/employees` sketched in
the original requirements) because a user can belong to several organizations: the path
says which one, and the existing organization access check applies unchanged. An employee
ID from another organization returns `404 employee_not_found`, exactly like a random ID.

### Employee object

```json
{
  "id": "41932c99-...", "organization_id": "30ce6c87-...",
  "employee_number": "E-1001", "first_name": "Grace", "last_name": "Hopper",
  "full_name": "Grace Hopper", "email": "grace.hopper@acme.example",
  "department": {"id": "...", "name": "Engineering"},
  "designation": "Staff Engineer",
  "manager": {"id": "...", "employee_number": "E-1", "full_name": "Ada Lovelace"},
  "location": "Bengaluru", "employment_status": "active",
  "joining_date": "2024-01-15", "termination_date": null, "archived_at": null,
  "created_at": "2026-11-11T14:09:36.03Z", "updated_at": "2026-11-11T14:09:36.03Z",
  "version": 3
}
```

`GET`, `POST`, `PATCH` and terminate responses also carry `ETag: "3"` (the version).
`PATCH`, `POST .../terminate` and `DELETE` accept `If-Match: "3"` (also `W/"3"`, `3`, or
`*` for any version). If the employee's version is different the answer is
`412 version_conflict` and nothing changes; without `If-Match` the last write wins as
before ([docs/14, section 3](14-data-integrity.md#3-optimistic-concurrency-on-employees)).

### `POST .../employees`

| Field | Required | Rules |
|---|---|---|
| employee_number | yes | 1-50 chars, starts with a letter or digit, then letters, digits, `.`, `_`, `-`; unique per organization |
| first_name, last_name | yes | 1-100 chars after trimming |
| email | yes | valid email, stored lowercase; unique per organization |
| joining_date | yes | ISO date `YYYY-MM-DD` |
| department_id | no | must be a department of this organization |
| manager_id | no | must be a non-terminated employee of this organization |
| designation, location | no | 1-150 chars after trimming |
| employment_status | no | `active` (default) or `on_leave`. `terminated` is rejected - use `/terminate` |

`201` with the employee object. Errors: `409 employee_number_taken | email_taken`,
`422 validation_error | department_not_found | manager_not_found | manager_terminated |
idempotency_key_reused`.

**Idempotency.** Optional header `Idempotency-Key` (1-255 printable ASCII characters, e.g. a
UUID). A repeat with the same key and body by the same user within
`IDEMPOTENCY_TTL_HOURS` (24) returns the first `201` and body with
`Idempotent-Replayed: true` and creates nothing; the same key with a different body is
`422 idempotency_key_reused`; failed requests are not remembered ([docs/13](13-idempotency.md#4-incoming-idempotency-key-on-post-employees)).

### `PATCH .../employees/{employee_id}`

Any subset of the create fields. Rules on top of the create rules:
- `null` clears `department_id`, `manager_id`, `designation`, `location`; `null` for a
  required field is `422`.
- `employment_status` may move between `active` and `on_leave` only.
- A terminated employee cannot be modified: `409 employee_terminated`.
- A new manager must not report (directly or indirectly) to this employee: `422 manager_cycle`.
- A body that changes nothing returns `200` and emits no event.

### `POST .../employees/{employee_id}/terminate`

Body optional: `{"termination_date": "2026-03-31"}`; defaults to today (UTC).
Sets `employment_status = terminated` and `termination_date`. Direct reports are moved to
the terminated employee's own manager (or to no manager if there is none), in the same
transaction. Termination is final in this version (no rehire). Errors:
`409 employee_terminated`, `422 termination_before_joining`.

### `DELETE .../employees/{employee_id}` - archive

Soft delete: sets `archived_at`. Allowed only for terminated employees
(`409 employee_not_terminated` otherwise). Idempotent - archiving again returns `204` and
changes nothing. Archived employees stay readable by ID and are hidden from the list unless
`include_archived=true`. Nothing is physically deleted, so history remains intact.

### `GET .../employees` - search, filters, sorting, pagination

| Query parameter | Meaning |
|---|---|
| `search` | Case-insensitive substring match on full name, email or employee number. `%` and `_` are matched literally (escaped), not as wildcards. 1-100 chars |
| `department_id`, `manager_id` | Exact match (`manager_id` lists direct reports) |
| `employment_status` | `active`, `on_leave` or `terminated` |
| `location` | Exact match, case-insensitive |
| `joined_from`, `joined_to` | Inclusive joining-date range (`422 invalid_date_range` if reversed) |
| `include_archived` | `false` by default |
| `sort` | `last_name` (default), `-last_name`, `joining_date`, `-joining_date`, `employee_number`, `-created_at` |
| `limit`, `offset` | Page size 1-100 (default 20), offset (default 0) |

Filters combine with AND. Example:
`GET .../employees?department_id=...&location=pune&sort=-joining_date&limit=10`

**Pagination strategy:** offset pagination with a total count, chosen because the admin UI
(Phase 8) needs page numbers and the data set per organization is modest. Sorting always
appends `id`, so equal sort values (two people named "Shah") cannot make rows repeat or
disappear between pages - covered by `test_pagination_is_stable_and_complete`. Keyset
(cursor) pagination is the upgrade path for very large organizations.

### Lifecycle events

Each successful write is classified into events by comparing the employee's tracked fields
before and after (`app/events/lifecycle.py`). One request can produce several events; each
changed field appears in exactly one of them:

| Change | Event |
|---|---|
| New employee | `employee.created` |
| Status becomes `terminated` (with `termination_date`) | `employee.terminated` |
| `department_id` changed | `employee.department_changed` |
| `manager_id` changed | `employee.manager_changed` |
| Any other tracked field | `employee.updated` |

Since Phase 5 every event is stored (`integration_events`, plus an `outbox_events` row) in
the **same database transaction** as the employee change, and processed asynchronously by
workers ([docs/09](09-event-driven-architecture.md)). The employee endpoints therefore
return as soon as the change is committed; external applications are updated shortly after.
Events can be followed through the events API (section 9). After the commit, each event is
also logged as `{"message": "employee lifecycle event", "event_type", "event_id",
"organization_id", "employee_id", "changed_fields"}` - IDs and field names only, never names
or emails. The request ID becomes the event's `correlation_id`.

## 7. Connectors

Design and error categories: [connector framework](10-connector-framework.md).

| Method and path | Permission | Notes |
|---|---|---|
| `GET /api/v1/connector-types` | any authenticated user | Catalog: type, version, auth type, `simulated`, operations, JSON schemas for `config` and `credentials` |
| `GET .../connectors` | `connectors:read` | Paginated, sorted by name |
| `POST .../connectors` | `connectors:manage` | Create; credentials encrypted; `201`, status `pending` |
| `GET .../connectors/{connector_id}` | `connectors:read` | |
| `PATCH .../connectors/{connector_id}` | `connectors:manage` | `name`, `config`, `credentials` (any subset). Changing config or credentials resets status to `pending`; credentials on a disconnected connector reconnect it |
| `POST .../connectors/{connector_id}/test` | `connectors:manage` | Live read-only call. **Always `200` when the test ran** - `ok` and `error` say how it went; `409 connector_disconnected` if there are no credentials |
| `POST .../connectors/{connector_id}/disconnect` | `connectors:manage` | Deletes the credentials; idempotent |
| `POST .../connectors/{connector_id}/operations` | `connectors:manage` | Run one operation for one employee now (manual sync) |
| `GET .../connectors/{connector_id}/accounts` | `connectors:read` | Employees linked to accounts in this application |

(`...` = `/api/v1/organizations/{organization_id}`.) Integration Managers and Organization
Admins hold `connectors:manage`; every member holds `connectors:read`.

### Create

```json
POST .../connectors
{"connector_type": "google_workspace", "name": "Google (acme.example)",
 "config": {"customer": "my_customer"},
 "credentials": {"client_id": "syncforge-local", "client_secret": "mock-google-client-secret"}}
```

`201`:
```json
{"id": "...", "connector_type": "google_workspace", "name": "Google (acme.example)",
 "version": "1.0.0", "simulated": true, "config": {"customer": "my_customer"},
 "status": "pending", "last_tested_at": null, "last_error": null,
 "credentials": {"auth_type": "oauth2_client_credentials", "fingerprint": "...cret",
                 "updated_at": "..."},
 "created_at": "...", "updated_at": "..."}
```

Credentials are never returned. Per type: Slack `{"token"}`, Google
`{"client_id", "client_secret"}`, payroll `{"api_key"}`. Optional `config.base_url`
overrides the default endpoint and must be an allowed host. Optional
`config.rate_limit_per_minute` (1-10000) paces SyncForge's calls to this connector across
all workers ([docs/12, section 8](12-reliability-and-retries.md#8-rate-limits-and-timeouts)).

Every connector response also contains the circuit breaker state:
`"circuit": {"state": "closed" | "open" | "half_open", "consecutive_failures": 0,
"open_until": null}` ([docs/12, section 7](12-reliability-and-retries.md#7-the-circuit-breaker)).

### Test

`200` `{"ok": true, "status": "connected", "tested_at": "...", "latency_ms": 12.4,
"detail": "SCIM API reachable.", "error": null}` - or on failure
`{"ok": false, "status": "error", ..., "error": {"category": "authentication",
"code": "http_401", "retryable": false, "retry_after": null, ...}}`. A successful test also
closes the connector's circuit breaker.

### Operations

Request: `{"operation": "create_user" | "update_user" | "deactivate_user" | "get_user",
"employee_id": "..."}`

`200`: `{"operation": "create_user", "connector_id": "...", "employee_id": "...",
"external_id": "U4F2A9C1B0E", "external_active": true, "account_status": "active",
"latency_ms": 9.8}`

Rules: `create_user` requires no existing link and a non-terminated employee; the other
operations require a link (`409 not_linked`). External failures return
`502 connector_error` with the normalized error in `details`; nothing is linked when
`create_user` fails. This manual endpoint makes **one** attempt and sends no idempotency
key; retries apply to workflow steps ([docs/12](12-reliability-and-retries.md)). It does go
through the connector's circuit breaker (`502` with category `circuit_open` while it is
open).

## 8. Workflows - `/api/v1/organizations/{organization_id}/workflows`

Design and execution semantics: [workflow engine](11-workflow-engine.md).

| Method and path | Permission | Notes |
|---|---|---|
| `GET .../workflows` | `workflows:read` | Paginated, sorted by name. Filters: `trigger_event_type`, `is_active` |
| `POST .../workflows` | `workflows:manage` | Create; **starts inactive**; `201` |
| `GET .../workflows/{workflow_id}` | `workflows:read` | |
| `PATCH .../workflows/{workflow_id}` | `workflows:manage` | `name`, `description`, `trigger_event_type`, `steps` (replaces the whole list). Trigger or step changes increment `version` |
| `POST .../workflows/{workflow_id}/activate` | `workflows:manage` | Idempotent; `409 connector_disconnected` if a step's connector is disconnected |
| `POST .../workflows/{workflow_id}/deactivate` | `workflows:manage` | Idempotent; history is kept |
| `GET .../workflows/{workflow_id}/executions` | `workflows:read` | Newest first, with per-step jobs. Filter: `execution_status` (`running`, `succeeded`, `failed`) |

Every member holds `workflows:read`; Integration Managers and Organization Admins hold
`workflows:manage`. There is no delete endpoint: deactivate instead, so execution history
stays readable.

### Create

```json
POST .../workflows
{"name": "Onboarding", "description": "Accounts for new hires.",
 "trigger_event_type": "employee.created",
 "steps": [{"connector_id": "<slack id>", "operation": "create_user"},
           {"connector_id": "<google id>", "operation": "create_user"},
           {"connector_id": "<payroll id>", "operation": "create_user"}]}
```

`201`:
```json
{"id": "...", "name": "Onboarding", "description": "Accounts for new hires.",
 "trigger_event_type": "employee.created", "is_active": false, "version": 1,
 "steps": [{"position": 1, "connector_id": "...", "connector_name": "slack",
            "connector_type": "slack", "operation": "create_user"}, ...],
 "created_at": "...", "updated_at": "..."}
```

Validation: 1 to 20 steps; triggers are the five `employee.*` event types; operations are
`create_user`, `update_user`, `deactivate_user`; each connector must belong to the
organization (`422 connector_not_found`); a connector + operation pair at most once
(`422 duplicate_step`); names unique (`409 workflow_name_taken`).

### Execution object

Returned by `.../executions` and inside an event's detail:

```json
{"id": "...", "event_id": "...", "event_type": "employee.created", "employee_id": "...",
 "workflow_id": "...", "workflow_name": "Onboarding", "workflow_version": 1,
 "status": "failed", "started_at": "...", "finished_at": "...",
 "jobs": [{"position": 1, "connector_id": "...", "operation": "create_user",
           "status": "succeeded", "attempts": 1, "external_id": "U4C78E57EE5",
           "error_category": null, "error_message": null, "started_at": "...", "finished_at": "..."},
          {"position": 3, "connector_id": "...", "operation": "create_user",
           "status": "failed", "attempts": 1, "external_id": null,
           "error_category": "server", "error_message": "Simulated failure (503).", ...}]}
```

Job `status`: `pending`, `running`, `succeeded`, `failed`, `skipped` (`error_message` then
says why, e.g. "The employee has no account in this application.").

## 9. Events - `/api/v1/organizations/{organization_id}/events`

Read-only. Events are created by employee changes and processed by workers.

| Method and path | Permission | Notes |
|---|---|---|
| `GET .../events` | `events:read` | Newest first. Filters: `event_status` (`pending`, `processing`, `retrying`, `completed`, `dead_letter`), `event_type`, `employee_id` |
| `GET .../events/{event_id}` | `events:read` | The event plus every workflow execution it triggered, with jobs |
| `GET .../events/{event_id}/attempts` | `events:read` | Every external call made for the event, ordered by execution, step and attempt number |

Every member holds `events:read`.

```json
{"id": "...", "event_type": "employee.created", "employee_id": "...",
 "changed_fields": ["email", "employee_number", "employment_status", "first_name",
                    "joining_date", "last_name"],
 "status": "completed", "correlation_id": "demo-hire-2", "attempts": 1,
 "created_at": "...", "started_at": "...", "completed_at": "...", "last_error": null,
 "executions": [ ... ]}
```

**Privacy:** events expose *which* fields changed, never the old or new values (names,
emails); `test_events_are_listed_without_personal_data` checks that the values do not appear
in the response. The values stay in the database for workers and the audit log.

`attempts` above 1 means the event was redelivered, recovered after a worker failure, or
retried. `next_attempt_at` is set while the event is `retrying`. Jobs carry
`next_attempt_at` too.

Attempt object (`GET .../events/{event_id}/attempts`):

```json
{"job_id": "...", "execution_id": "...", "position": 3, "connector_id": "...",
 "operation": "create_user", "attempt_number": 2,
 "started_at": "...", "finished_at": "...", "duration_ms": 12.8,
 "outcome": "failed", "error_category": "server", "error_code": "http_503",
 "error_message": "payroll: Simulated failure (503).", "http_status": 503,
 "retryable": true, "retry_after_seconds": null, "next_attempt_at": "..."}
```

`outcome` is `succeeded`, `failed`, `skipped`, `interrupted` (the worker stopped during the
call), or `null` while the call is in progress.

## 10. Dead-letter queue - `/api/v1/organizations/{organization_id}/dead-letter-events`

Events that failed for good ([docs/12, section 5](12-reliability-and-retries.md#5-the-dead-letter-queue)).

| Method and path | Permission | Notes |
|---|---|---|
| `GET .../dead-letter-events` | `events:read` | Newest first. Filters: `entry_status` (`open`, `replayed`), `connector_id` |
| `GET .../dead-letter-events/{entry_id}` | `events:read` | The entry, the event's current state (`event`) and every dead-letter round of that event (`history`) |
| `POST .../dead-letter-events/{entry_id}/replay` | **`events:replay`** | `202 Accepted`: the event is requeued; only failed steps (and those skipped because of them) run again, each with a fresh retry budget. `409 already_replayed`, `409 workflow_inactive` |

`events:replay` is held by Integration Managers and Organization Admins, not by Viewers: a
replay makes real calls to external applications.

```json
{"id": "...", "event_id": "...", "event_type": "employee.created", "employee_id": "...",
 "reason": "retries_exhausted", "job_id": "...", "connector_id": "...",
 "operation": "create_user", "error_category": "server", "error_code": "http_503",
 "http_status": 503, "error_message": "Gave up after 5 attempts: payroll: Simulated failure (503).",
 "attempts": 5, "failed_steps": 1, "dead_lettered_at": "...",
 "status": "open", "replayed_at": null, "replayed_by_user_id": null}
```

`reason` is `retries_exhausted` (a retryable error outlasted the retry budget) or
`non_retryable` (credentials, permissions, invalid data, configuration). Like events, entries
contain no employee names or emails.

## 11. Audit log - `/api/v1/organizations/{organization_id}/audit-logs`

| Method and path | Permission | Notes |
|---|---|---|
| `GET .../audit-logs` | **`audit:read`** (Organization Admin, Integration Manager) | Newest first. Filters: `action` (exact, or a prefix ending in a dot such as `employee.`), `resource_type`, `resource_id`, `actor_user_id`, `outcome` (`success`, `failure`), `since`, `until`; `limit` (default 50), `offset` |

```json
{"id": 7, "created_at": "...", "actor_type": "user", "actor_user_id": "...",
 "action": "employee.updated", "resource_type": "employee", "resource_id": "...",
 "outcome": "success",
 "details": {"changed_fields": ["designation"], "events": ["employee.updated"],
             "values": {"designation": {"from": "Engineer", "to": "Staff Engineer"}}},
 "request_id": "ad6821ad658d4049a47e12f99052a94e"}
```

Read-only: there is no endpoint (and, thanks to a trigger, no SQL) that changes entries.
The list of actions and what each records: [docs/14, section 2](14-data-integrity.md#2-the-audit-log).

## 12. Data integrity - policies, reconciliation, conflicts

| Method and path | Permission | Notes |
|---|---|---|
| `GET .../data-source-policies` | `conflicts:read` | The effective policy for each of the seven fields (`configured: false` = built-in default) |
| `PUT .../data-source-policies/{field}` | **`policies:manage`** (Organization Admin) | `{"source": "syncforge" \| "connector", "connector_id": ..., "resolution_mode": "manual" \| "auto", "severity": "low" \| "medium" \| "high" \| "critical"}` |
| `POST .../connectors/{connector_id}/reconcile` | `conflicts:resolve` | Compare linked accounts with the application (up to 500). Returns `accounts_checked`, `conflicts_opened`, `conflicts_refreshed`, `conflicts_closed`, `auto_resolved`, `errors` |
| `GET .../conflicts` | `conflicts:read` | Filters: `conflict_status` (`open`, `resolved`, `dismissed`), `severity`, `field`, `employee_id`, `connector_id` |
| `GET .../conflicts/{conflict_id}` | `conflicts:read` | The conflict with its `resolutions` history |
| `POST .../conflicts/{conflict_id}/resolve` | `conflicts:resolve` (+ `employees:write` for `use_external`, except `account_active`) | `{"resolution": "use_syncforge" \| "use_external" \| "dismiss", "note": "...", "override": false}` |

Conflict object:

```json
{"id": "...", "employee_id": "...", "connector_id": "...", "field": "department",
 "syncforge_value": "Engineering", "external_value": "Finance",
 "authoritative_source": "syncforge", "severity": "medium", "status": "open",
 "employee_version": 1, "first_detected_at": "...", "last_detected_at": "...",
 "times_detected": 1, "resolved_at": null}
```

Resolution rules and errors (`resolution_against_policy`, `note_required`,
`conflict_stale`, `department_not_found`, `reactivation_not_supported`,
`conflict_not_open`, `502` when the application refuses): [docs/14, section 6](14-data-integrity.md#6-conflict-resolution).

## 13. PowerShell examples

```powershell
$base = "http://127.0.0.1:8000/api/v1/auth"
$login = Invoke-RestMethod -Method Post "$base/login" -ContentType "application/json" `
  -Body '{"email":"ada@acme.example","password":"correct-horse-battery"}'
$h = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod "$base/me" -Headers $h
Invoke-RestMethod -Method Post "$base/logout" -Headers $h
```

```powershell
$api = "http://127.0.0.1:8000/api/v1"
$org = Invoke-RestMethod -Method Post "$api/organizations" -Headers $h -ContentType "application/json" `
  -Body '{"name":"Acme Corp"}'
Invoke-RestMethod -Method Post "$api/organizations/$($org.id)/members" -Headers $h `
  -ContentType "application/json" -Body '{"email":"bob@acme.example","role":"viewer"}'
Invoke-RestMethod "$api/organizations/$($org.id)/members" -Headers $h
```

```powershell
# Employees (after logging in as above and creating $org)
$emp = "$api/organizations/$($org.id)/employees"
$dept = Invoke-RestMethod -Method Post "$api/organizations/$($org.id)/departments" -Headers $h `
  -ContentType "application/json" -Body '{"name":"Engineering"}'
$body = @{ employee_number = "E-1001"; first_name = "Grace"; last_name = "Hopper";
           email = "grace@acme.example"; department_id = $dept.id; joining_date = "2024-01-15" } |
        ConvertTo-Json
$grace = Invoke-RestMethod -Method Post $emp -Headers $h -ContentType "application/json" -Body $body
Invoke-RestMethod "${emp}?search=hop&sort=-joining_date" -Headers $h
Invoke-RestMethod -Method Post "$emp/$($grace.id)/terminate" -Headers $h `
  -ContentType "application/json" -Body '{"termination_date":"2026-12-31"}'
```

```powershell
# Connectors (mock services running - see mock-services/README.md)
$con = "$api/organizations/$($org.id)/connectors"
$slack = Invoke-RestMethod -Method Post $con -Headers $h -ContentType "application/json" `
  -Body '{"connector_type":"slack","name":"Slack","credentials":{"token":"xoxp-mock-local-token"}}'
Invoke-RestMethod -Method Post "$con/$($slack.id)/test" -Headers $h
$op = @{ operation = "create_user"; employee_id = $grace.id } | ConvertTo-Json
Invoke-RestMethod -Method Post "$con/$($slack.id)/operations" -Headers $h -ContentType "application/json" -Body $op
```

```powershell
# Workflows and events (API, worker, relay and mocks running - see docs/09, section 10)
$wf = "$api/organizations/$($org.id)/workflows"
$body = @{ name = "Onboarding"; trigger_event_type = "employee.created";
           steps = @(@{ connector_id = $slack.id; operation = "create_user" }) } | ConvertTo-Json -Depth 5
$onboarding = Invoke-RestMethod -Method Post $wf -Headers $h -ContentType "application/json" -Body $body
Invoke-RestMethod -Method Post "$wf/$($onboarding.id)/activate" -Headers $h
# ... create an employee (as above), then:
$events = Invoke-RestMethod "$api/organizations/$($org.id)/events?event_type=employee.created" -Headers $h
Invoke-RestMethod "$api/organizations/$($org.id)/events/$($events.items[0].id)" -Headers $h
Invoke-RestMethod "$api/organizations/$($org.id)/events/$($events.items[0].id)/attempts" -Headers $h
```

```powershell
# Idempotent create: run twice - same employee, second response replayed
$key = [guid]::NewGuid().ToString()
$body = @{ employee_number = "E-2001"; first_name = "Ada"; last_name = "Lovelace";
           email = "ada.l@acme.example"; joining_date = "2026-11-01" } | ConvertTo-Json
$r = Invoke-WebRequest -Method Post $emp -Headers ($h + @{ "Idempotency-Key" = $key }) `
  -ContentType "application/json" -Body $body
$r.StatusCode; $r.Headers["Idempotent-Replayed"]

# Dead-letter queue: list open entries and replay the first one
$dlq = "$api/organizations/$($org.id)/dead-letter-events"
$open = Invoke-RestMethod "${dlq}?entry_status=open" -Headers $h
Invoke-RestMethod -Method Post "$dlq/$($open.items[0].id)/replay" -Headers $h
```

```powershell
# Optimistic concurrency: save only if nobody changed the employee since you read it
# (Ada from the idempotency example above; Grace was terminated earlier)
$ada = $r.Content | ConvertFrom-Json
$e = Invoke-WebRequest "$emp/$($ada.id)" -Headers $h
$etag = $e.Headers["ETag"]
Invoke-RestMethod -Method Patch "$emp/$($ada.id)" -Headers ($h + @{ "If-Match" = $etag }) `
  -ContentType "application/json" -Body '{"location":"Pune"}'

# Data integrity: reconcile a connector, list open conflicts, let HR's value win
Invoke-RestMethod -Method Post "$con/$($slack.id)/reconcile" -Headers $h
$open = Invoke-RestMethod "$api/organizations/$($org.id)/conflicts?conflict_status=open" -Headers $h
Invoke-RestMethod -Method Post "$api/organizations/$($org.id)/conflicts/$($open.items[0].id)/resolve" `
  -Headers $h -ContentType "application/json" -Body '{"resolution":"use_syncforge"}'

# Audit trail of employee changes
Invoke-RestMethod "$api/organizations/$($org.id)/audit-logs?action=employee." -Headers $h
```
