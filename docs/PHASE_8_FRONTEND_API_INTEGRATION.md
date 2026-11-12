# Phase 8 — Frontend API integration

How the Angular application talks to the SyncForge API: where the types come from, which
service calls which endpoint, and how headers, paging, errors and background processing
are handled. The backend's own reference is [08-api-design.md](08-api-design.md).

No backend endpoint was added or changed for the frontend. The one backend change in
Phase 8 was the password minimum (12 → 8 characters), made at the owner's request.

## 1. Coverage

The OpenAPI snapshot lists **53 operations**. The frontend uses **51**: every
`/api/v1` operation. The two it does not call are `GET /health` and `GET /ready`, which
are infrastructure probes for load balancers and orchestration, not user features.
(These counts describe the end of Phase 8. Phase 9 adds `GET /auth/activity`, used by
Settings, and the Super Admin endpoint `GET /security-events`, which has no screen.)

## 2. Types generated from the OpenAPI document

```
backend (FastAPI) ──► frontend/openapi/openapi.json ──► npm run api:types ──► src/app/core/api/schema.d.ts
                                                                             │
                                                     core/api/models.ts ◄────┘  friendly aliases
```

- `npm run api:types` runs `openapi-typescript` 7.13.0 on the committed snapshot
  `frontend/openapi/openapi.json`. `schema.d.ts` is generated and never edited by hand.
- `models.ts` gives the generated schemas readable names
  (`Employee = components['schemas']['EmployeeResponse']`, and so on) plus a generic
  `Page<T>` (`items`, `total`, `limit`, `offset`).
- `npm run api:check` regenerates the types into a temporary file and fails if they differ
  from the committed ones, so the frontend cannot silently drift from the API contract.
  When the backend changes, refresh the snapshot from the running API
  (`/openapi.json`), run `api:types`, and let the compiler point at every affected screen.

## 3. HTTP layer

| Piece | File | Role |
|---|---|---|
| `API_BASE` = `/api/v1` | `core/api/http-util.ts` | Same-origin base path; the dev server proxies it to `127.0.0.1:8000` |
| `orgUrl(orgId, …segments)` | same | Builds `/api/v1/organizations/{org}/…` with every segment URL-encoded |
| `query(values)` | same | Query parameters with empty values dropped, so "no filter" sends nothing |
| `etag(version)` | same | Strong ETag `"<version>"` for `If-Match` |
| `authInterceptor` | `core/auth/interceptors.ts` | Adds `Authorization: Bearer …` to `/api/v1` requests only, never to other origins |
| `errorInterceptor` | same | Converts every failure into `ApiError`; on 401 ends the session and returns to login with `returnUrl` |
| `ApiError` | `core/api/api-error.ts` | `status`, `code`, `message`, `details`, `requestId` (from `X-Request-ID`), `isNetwork`, `fieldIssues` |

Each API area has one injectable service. A method ending in `Request` returns an
`HttpResourceRequest` for `httpResource` (reads that follow signals); the others return
`Observable`s (writes, and reads used in `forkJoin`).

## 4. Endpoint map

`{org}` = `/api/v1/organizations/{organization_id}`.

### `AuthApi` (`core/api/auth.api.ts`)

| Method | HTTP |
|---|---|
| `login` | `POST /api/v1/auth/login` |
| `register` | `POST /api/v1/auth/register` |
| `me` | `GET /api/v1/auth/me` |
| `logout` | `POST /api/v1/auth/logout` |
| `activityRequest` | `GET /api/v1/auth/activity` (added in Phase 9, "Recent sign-ins" in Settings) |

### `OrganizationsApi` (`core/api/organizations.api.ts`)

| Method | HTTP |
|---|---|
| `listRequest` | `GET /api/v1/organizations` |
| `create` | `POST /api/v1/organizations` |
| `get` / `rename` | `GET` / `PATCH {org}` |
| `membersRequest`, `listMembers` | `GET {org}/members` |
| `addMember` | `POST {org}/members` |
| `changeRole` / `removeMember` | `PATCH` / `DELETE {org}/members/{user_id}` |

### `EmployeesApi`, `DepartmentsApi` (`core/api/workforce.api.ts`)

| Method | HTTP | Headers |
|---|---|---|
| `listRequest`, `list` | `GET {org}/employees` | |
| `getRequest`, `get` | `GET {org}/employees/{id}` | |
| `create` | `POST {org}/employees` | `Idempotency-Key` |
| `update` | `PATCH {org}/employees/{id}` | `If-Match` |
| `terminate` | `POST {org}/employees/{id}/terminate` | `If-Match` |
| `archive` | `DELETE {org}/employees/{id}` | `If-Match` |
| departments `listRequest`, `list`, `create`, `rename`, `delete` | `GET` / `POST {org}/departments`, `PATCH` / `DELETE {org}/departments/{id}` | |

### `ConnectorsApi`, `WorkflowsApi` (`core/api/integrations.api.ts`)

| Method | HTTP |
|---|---|
| `typesRequest` | `GET /api/v1/connector-types` (plain array) |
| `listRequest`, `list` / `create` | `GET` / `POST {org}/connectors` |
| `getRequest`, `get` / `update` | `GET` / `PATCH {org}/connectors/{id}` |
| `test`, `disconnect`, `reconcile` | `POST {org}/connectors/{id}/test`, `/disconnect`, `/reconcile` |
| `runOperation` | `POST {org}/connectors/{id}/operations` |
| `accountsRequest` | `GET {org}/connectors/{id}/accounts` |
| workflows `listRequest`, `list` / `create` | `GET` / `POST {org}/workflows` |
| `getRequest`, `get` / `update` | `GET` / `PATCH {org}/workflows/{id}` |
| `setActive(true / false)` | `POST {org}/workflows/{id}/activate` / `/deactivate` |
| `executionsRequest`, `executions` | `GET {org}/workflows/{id}/executions` |

### `EventsApi`, `DeadLettersApi`, `ConflictsApi`, `AuditApi` (`core/api/operations.api.ts`)

| Method | HTTP |
|---|---|
| events `listRequest`, `list` | `GET {org}/events` |
| `getRequest` | `GET {org}/events/{id}` |
| `attemptsRequest` | `GET {org}/events/{id}/attempts` (plain array) |
| dead letters `listRequest`, `list` / `getRequest` | `GET {org}/dead-letter-events`, `/{id}` |
| `replay` | `POST {org}/dead-letter-events/{id}/replay` |
| conflicts `listRequest`, `list` / `getRequest` | `GET {org}/conflicts`, `/{id}` |
| `resolve` | `POST {org}/conflicts/{id}/resolve` |
| `policiesRequest` / `updatePolicy` | `GET {org}/data-source-policies` (plain array) / `PUT {org}/data-source-policies/{field}` |
| audit `listRequest`, `list` | `GET {org}/audit-logs` |

## 5. Conventions the frontend relies on

### Paging

Lists use `limit` and `offset` and return `{items, total, limit, offset}`; the API caps
`limit` at 100. `<sf-pagination>` works directly on those values, and the offset is kept
in the URL. Three endpoints return plain arrays instead of a page (marked above).

### Totals without aggregate endpoints

The API has no count or statistics endpoints. The dashboard and reliability overview read
a total by requesting `limit=1` with the relevant filter and using `total`. Daily history
comes from audit-log totals in one-day `since`/`until` windows (`workflow.executed` with
outcome success / failure, `sync.retry_scheduled`). Each figure is requested separately,
so one failure marks only that figure as unavailable.

### Optimistic concurrency (`If-Match`)

Employees carry a `version`. Edit, terminate and archive send `If-Match: "<version>"`.
If someone else saved in between, the API answers **412** and the dialog offers
"Load latest", which loads the current version into the form and discards the stale edit,
so the user can reapply their change knowingly. Edits send only the fields that changed.

### Idempotent create (`Idempotency-Key`)

The add-employee dialog generates one `crypto.randomUUID()` when it opens and sends it
with every submit from that dialog. A double click or a retry after a network error
therefore returns the first result instead of creating a second employee.

### Validation errors (422)

`ApiError.fieldIssues` reads `details` (`[{field, message}]`, with `body.` / `query.`
prefixes removed). `applyServerErrors()` puts each message on the matching form control;
messages without a matching control are listed above the form.

### Business-rule refusals (409)

Shown with the API's message. Where the details help, the UI uses them: workflow
activation lists the disconnected connectors (`details.connectors`); member removal
explains the last-admin rule; conflict resolution distinguishes `conflict_stale` (the
employee changed — reconcile again) from a policy override that needs a note.

### Connector errors (502)

Connection tests and manual operations return the connector framework's normalized error
(category such as `authentication`, `rate_limited`, `timeout`, `network`, `server`, plus
message). The UI
shows the category and message and never shows credentials; credentials are write-only
and only their fingerprint is displayed.

### API not reachable

A status 0, or a 502/503/504 that does not carry the API's error envelope (that is, the
dev-server proxy answered because the API is down), becomes `api_unreachable` with the
message "The SyncForge API could not be reached". Before this rule existed, a stopped API
showed up as a confusing "502" on the login page.

## 6. Following background processing

Events, workflow steps, retries and dead letters change in the background (Celery worker
and outbox relay). The API has no WebSocket or server-sent events, so the UI polls:

- the event page reloads every few seconds until the event reaches a final state;
- lists have an optional "Auto-refresh (5 s)" switch, active only while the tab is
  visible (`useAutoRefresh`);
- after an action that starts background work (hire, replay, reconcile), the page reloads
  the affected data; the resulting event can be followed on the Events screen.

## 7. Organization isolation

Every organization-scoped call contains the organization ID from the route. The frontend
does not decide whether the user may see it: `organizationGuard` asks the API, and the
API answers 404 for organizations the user does not belong to. The browser test "an
organization the user does not belong to is not shown" checks this end to end.

## 8. Changing the API safely

1. Change the backend and its tests.
2. Save the new OpenAPI document to `frontend/openapi/openapi.json`.
3. `npm run api:types`; fix the compile errors this reveals.
4. `npm run api:check`, `npm run test:ci`, `npm run e2e`.

Breaking API versioning (`/api/v2`) is Phase 9 work; the frontend's single `API_BASE`
constant is the place a version change would start.
