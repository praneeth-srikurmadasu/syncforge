# 08 - API Design

> **Scope:** endpoints implemented as of Phase 2. Live, always-current reference:
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
| Pagination | List endpoints take `limit` (1-100, default 20) and `offset` (default 0) and return `{"items", "total", "limit", "offset"}`. Order is stable (name, then id). |
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
| 422 | `validation_error` | Request body failed validation |
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

Permissions required per endpoint (see [security design](15-security-design.md#8-authorization-model)
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

## 5. PowerShell examples

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
