# 08 - API Design

> **Scope:** endpoints implemented as of Phase 4. Live, always-current reference:
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

### Error codes in use

| HTTP | `code` | Meaning |
|---|---|---|
| 401 | `not_authenticated` | No bearer token sent (or a non-Bearer scheme) |
| 401 | `invalid_token` | Malformed, wrongly signed, wrong issuer/audience/type, or user missing/inactive |
| 401 | `token_expired` | Token past its `exp` |
| 401 | `token_revoked` | Token was logged out |
| 401 | `invalid_credentials` | Login failed (same message for every cause) |
| 403 | `insufficient_role` | Member of the organization, but the role lacks the permission; `details.required_permission` names it |
| 404 | `not_found` | Unknown route |
| 404 | `organization_not_found` | Organization does not exist, is deactivated, or the caller is not a member |
| 404 | `user_not_found` | Adding a member: no active user has that email |
| 404 | `member_not_found` | The user is not a member of this organization |
| 405 | `method_not_allowed` | Wrong HTTP method |
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
| password | 12-128 characters |
| full_name | 1-200 characters after trimming whitespace |

`201`:
```json
{"id": "9728de53-...", "email": "ada@acme.example", "full_name": "Ada Lovelace",
 "is_active": true, "is_superadmin": false, "created_at": "2026-11-11T12:41:04.146404Z"}
```
Errors: `409 email_taken`, `422 validation_error`.
Idempotency: not idempotent - a repeat returns `409`.

### `POST /api/v1/auth/login`
Auth: none.

Request: `{"email": "ada@acme.example", "password": "correct-horse-battery"}`

`200`: `{"access_token": "eyJ...", "token_type": "bearer", "expires_in": 1800}`

Errors: `401 invalid_credentials` - identical for unknown email, wrong password and
inactive account. `422 validation_error`.

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
  "created_at": "2026-11-11T14:09:36.03Z", "updated_at": "2026-11-11T14:09:36.03Z"
}
```

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
`422 validation_error | department_not_found | manager_not_found | manager_terminated`.

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

In Phase 3 events are written to the application log as
`{"message": "employee lifecycle event", "event_type", "organization_id", "employee_id",
"changed_fields"}` - IDs and field names only, never names or emails. In Phase 5 the same
events are stored in the transactional outbox within the employee's database transaction
and processed by workers.

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
overrides the default endpoint and must be an allowed host.

### Test

`200` `{"ok": true, "status": "connected", "tested_at": "...", "latency_ms": 12.4,
"detail": "SCIM API reachable.", "error": null}` - or on failure
`{"ok": false, "status": "error", ..., "error": {"category": "authentication",
"code": "http_401", "retryable": false, "retry_after": null, ...}}`.

### Operations

Request: `{"operation": "create_user" | "update_user" | "deactivate_user" | "get_user",
"employee_id": "..."}`

`200`: `{"operation": "create_user", "connector_id": "...", "employee_id": "...",
"external_id": "U4F2A9C1B0E", "external_active": true, "account_status": "active",
"latency_ms": 9.8}`

Rules: `create_user` requires no existing link and a non-terminated employee; the other
operations require a link (`409 not_linked`). External failures return
`502 connector_error` with the normalized error in `details`; nothing is linked when
`create_user` fails. Operations are attempted **once** in Phase 4 (retries: Phase 6).

## 8. PowerShell examples

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
