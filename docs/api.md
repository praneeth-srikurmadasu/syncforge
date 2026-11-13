# API

The interactive reference is generated from the code. With the API running, open
**`/docs`** for Swagger UI, `/redoc`, or `/openapi.json`. In Docker that is
http://localhost:8080/docs. This page covers the conventions and gives an overview of the
58 operations.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1`. `/api/v2` holds only endpoints whose contract changed in a breaking way (section 4). `/health` and `/ready` are unversioned. |
| Authentication | `Authorization: Bearer <token>` from `POST /api/v1/auth/login`; tokens last 30 minutes, and logout revokes them |
| Tenant isolation | Under `/organizations/{organization_id}`, non-members get **404** (the organization's existence is not revealed) and members without the permission get **403** |
| Errors | Always `{"error": {"code", "message", "details", "request_id"}}`. Branch on `code`, not `message`. |
| Validation | `422 validation_error`, with `details` listing `{field, message, type}`; submitted values are never echoed |
| Pagination | `limit` (1-100) and `offset`, returning `{items, total, limit, offset}`. Every sort ends with `id`, so pages never overlap. |
| Partial updates | `PATCH` changes only the fields sent. `null` clears an optional field; unknown fields are rejected. |
| Tracing | Every response carries `X-Request-ID`. Send your own (`[A-Za-z0-9._-]{1,128}`) to correlate requests. |
| Idempotent create | `POST .../employees` accepts `Idempotency-Key`. A repeat returns the stored response with `Idempotent-Replayed: true`. |
| Concurrent edits | Employee responses carry `ETag: "<version>"`. `PATCH`, terminate and archive accept `If-Match` and answer `412 version_conflict` if the employee changed. |
| Limits | Request bodies over 1 MiB get `413`. Too many sign-in or registration attempts get `429` with `Retry-After`. |

## 2. Endpoints

`{org}` stands for `/api/v1/organizations/{organization_id}`. Permissions are listed per
role in [security](security.md#3-roles-and-permissions).

| Area | Endpoints | Permission |
|---|---|---|
| Probes | `GET /health` (liveness), `GET /ready` (database check, `503 not_ready` on failure) | none |
| Auth | `POST /api/v1/auth/register`, `POST .../login`, `GET .../me`, `POST .../logout`, `GET .../activity` (your recent sign-ins) | none / signed in |
| Organizations | `GET`, `POST /api/v1/organizations`; `GET`, `PATCH {org}` | `org:read`, `org:update` |
| Members | `GET`, `POST {org}/members`; `PATCH`, `DELETE {org}/members/{user_id}` (the last Organization Admin cannot be removed) | `members:read`, `members:manage` |
| Summary | `GET {org}/summary`: dashboard counts and processing-time percentiles for the last 24 h | `org:read` |
| Departments | `GET`, `POST {org}/departments`; `PATCH`, `DELETE .../{department_id}` (only when empty) | `departments:read`, `departments:manage` |
| Employees | `GET`, `POST {org}/employees`; `GET`, `PATCH .../{employee_id}`; `POST .../terminate`; `DELETE` (archive, terminated only) | `employees:read`, `employees:write` |
| Connectors | `GET /api/v1/connector-types`; `GET`, `POST {org}/connectors`; `GET`, `PATCH .../{connector_id}`; `POST .../test`, `.../disconnect`, `.../operations`; `GET .../accounts` | `connectors:read`, `connectors:manage` |
| Workflows | `GET`, `POST {org}/workflows`; `GET`, `PATCH .../{workflow_id}`; `POST .../activate`, `.../deactivate`; `GET .../executions` | `workflows:read`, `workflows:manage` |
| Events | `GET {org}/events`; `GET .../{event_id}` (executions and jobs); `GET .../{event_id}/attempts` (every external call) | `events:read` |
| Dead-letter queue | `GET {org}/dead-letter-events`; `GET .../{entry_id}`; `POST .../{entry_id}/replay` | `events:read`, `events:replay` |
| Data integrity | `GET {org}/data-source-policies`; `PUT .../{field}`; `POST {org}/connectors/{id}/reconcile`; `GET {org}/conflicts`; `GET .../{conflict_id}`; `POST .../resolve` | `conflicts:read`, `policies:manage`, `conflicts:resolve` |
| Audit log | `GET {org}/audit-logs` (filters: action, resource, actor, outcome, time range) | `audit:read` |
| Platform | `GET /api/v1/security-events`, `GET /api/v1/system/status` (worker and relay heartbeats, outbox backlog, stuck events) | Super Admin |
| v2 | `GET /api/v2/organizations/{organization_id}/employees` | `employees:read` |

## 3. Error codes

Every code is listed per endpoint in the OpenAPI document. These are the ones a client
handles most often:

| HTTP | Codes |
|---|---|
| 401 | `not_authenticated`, `invalid_token`, `token_expired`, `token_revoked`, `invalid_credentials` (same message for every cause) |
| 403 | `insufficient_role` (`details.required_permission`), `superadmin_required` |
| 404 | `organization_not_found`, `employee_not_found`, `connector_not_found`, `workflow_not_found`, `event_not_found`, `dead_letter_not_found`, `conflict_not_found` |
| 409 | Duplicates: `email_taken`, `employee_number_taken`, `department_name_taken`, `connector_name_taken`, `workflow_name_taken`. State: `employee_terminated`, `department_in_use`, `last_admin`, `connector_disconnected`, `already_replayed`, `conflict_stale` |
| 412 | `version_conflict` (`details.expected_version`, `details.current_version`) |
| 422 | `validation_error`, `manager_cycle`, `manager_terminated`, `duplicate_step`, `idempotency_key_reused`, `resolution_against_policy`, `invalid_cursor`, `host_not_allowed` |
| 429 | `rate_limited` (`Retry-After`) |
| 502 | `connector_error`: the external application failed; `details` holds the normalized category, code and whether it is retryable |
| 503 | `not_ready`, `encryption_not_configured` |

## 4. Versioning

The version is part of the path.
- **Additive changes stay in v1:** new endpoints, optional parameters, response fields and
  error codes. Clients must ignore unknown fields.
- **Breaking changes get a new version.** That version contains only the endpoints that
  changed, and v1 stays supported, so clients move one endpoint at a time.
- **Retiring a version** would mean `Deprecation` and `Sunset` headers (RFC 9745,
  RFC 8594) for a release cycle before removal.

Full reasoning: [ADR-0021](adr/0021-path-versioning-and-keyset-pagination.md).

**The v2 employee list** keeps v1's filters and permission and changes the paging model:

| | v1 | v2 |
|---|---|---|
| Envelope | `{items, total, limit, offset}` | `{data, page: {limit, next_cursor, has_more}}` |
| Paging | `offset` | opaque `cursor` (keyset) |
| Rows added or removed while paging | later pages shift (duplicates or gaps) | no duplicates or gaps |
| Deep page cost | grows with the offset | about the same as page 1 |

Each page asks for rows strictly after the last key seen:
`WHERE (last_name, first_name, id) > (:last, :first, :id) ORDER BY ... LIMIT n+1`. The
extra row tells whether a next page exists. The cursor is base64url JSON with the sort,
the last key and a fingerprint of the organization and filters. A cursor reused with
different filters, sort or organization gets `422 invalid_cursor`. The web application
keeps using v1, because it shows totals and page numbers. v2 is for integrations that
walk the whole directory.

## 5. Example

```bash
API=http://localhost:8080/api/v1
TOKEN=$(curl -s -X POST $API/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"<password>"}' | jq -r .access_token)

ORG=$(curl -s $API/organizations -H "Authorization: Bearer $TOKEN" | jq -r '.items[0].id')

# Hire someone: returns 201 at once; the onboarding workflow runs in the background
curl -s -X POST $API/organizations/$ORG/employees \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"employee_number":"E-1001","first_name":"Ada","last_name":"Lovelace",
       "email":"ada@example.com","joining_date":"2026-11-13"}'

# Follow the resulting event
curl -s "$API/organizations/$ORG/events?limit=1" -H "Authorization: Bearer $TOKEN"
```
