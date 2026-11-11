# 08 — API Design

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

### Error codes in use

| HTTP | `code` | Meaning |
|---|---|---|
| 401 | `not_authenticated` | No bearer token sent (or a non-Bearer scheme) |
| 401 | `invalid_token` | Malformed, wrongly signed, wrong issuer/audience/type, or user missing/inactive |
| 401 | `token_expired` | Token past its `exp` |
| 401 | `token_revoked` | Token was logged out |
| 401 | `invalid_credentials` | Login failed (same message for every cause) |
| 404 | `not_found` | Unknown route |
| 405 | `method_not_allowed` | Wrong HTTP method |
| 409 | `email_taken` | Registration with an existing email (case-insensitive) |
| 422 | `validation_error` | Request body failed validation |
| 500 | `internal_error` | Unexpected server error (details only in logs) |
| 503 | `not_ready` | Readiness check failed (database unreachable) |

All 401 responses include `WWW-Authenticate: Bearer`.

## 2. Probes

### `GET /health`
Auth: none. `200 {"status": "ok", "service": "syncforge-api", "version": "0.2.0"}`

### `GET /ready`
Auth: none. `200 {"status": "ready", "checks": {"database": "ok"}}` ·
`503` with `code: not_ready`, `details: {"database": "unreachable"}`.

## 3. Authentication — `/api/v1/auth`

### `POST /api/v1/auth/register`
Auth: none. Creates a platform user who belongs to no organization yet.

Request:
```json
{"email": "ada@acme.example", "password": "correct-horse-battery", "full_name": "Ada Lovelace"}
```

| Field | Rules |
|---|---|
| email | valid email; normalised to lowercase |
| password | 12–128 characters |
| full_name | 1–200 characters after trimming whitespace |

`201`:
```json
{"id": "9728de53-...", "email": "ada@acme.example", "full_name": "Ada Lovelace",
 "is_active": true, "is_superadmin": false, "created_at": "2026-11-11T12:41:04.146404Z"}
```
Errors: `409 email_taken`, `422 validation_error`.
Idempotency: not idempotent — a repeat returns `409`.

### `POST /api/v1/auth/login`
Auth: none.

Request: `{"email": "ada@acme.example", "password": "correct-horse-battery"}`

`200`: `{"access_token": "eyJ...", "token_type": "bearer", "expires_in": 1800}`

Errors: `401 invalid_credentials` — identical for unknown email, wrong password and
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

## 4. PowerShell examples

```powershell
$base = "http://127.0.0.1:8000/api/v1/auth"
$login = Invoke-RestMethod -Method Post "$base/login" -ContentType "application/json" `
  -Body '{"email":"ada@acme.example","password":"correct-horse-battery"}'
$h = @{ Authorization = "Bearer $($login.access_token)" }
Invoke-RestMethod "$base/me" -Headers $h
Invoke-RestMethod -Method Post "$base/logout" -Headers $h
```
