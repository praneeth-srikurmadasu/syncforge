# Phase 8 - Frontend Implementation Plan

> Written after auditing the repository at commit `8a17b19` (Phase 7 complete: migrations
> `0001`-`0012`, 526 backend tests, 53 API operations). Everything below is derived from
> the code - routers, schemas, services and the live OpenAPI document - not from older
> status text. Features the backend does not support are marked **unsupported** and are not
> built as if they worked.

## 1. Verified implementation state

| Phase | Verified in code |
|---|---|
| 1-2 | FastAPI app, JWT auth (register, login, `/me`, logout with revocation), organizations, memberships, 3 organization roles + Super Admin, tenant isolation (`require_org_permission`: non-member 404, missing permission 403) |
| 3 | Departments, employees (CRUD, search, filters, sort, pagination, terminate, archive), lifecycle events |
| 4 | Connector framework: catalog, connectors CRUD, encrypted credentials (never returned), connection test, disconnect, manual operations, linked accounts; Slack / Google Workspace / payroll adapters against **simulated** local mocks |
| 5 | Workflows (CRUD, versioning, activate/deactivate, executions), integration events (transactional outbox, relay, Celery workers) |
| 6 | Retries with backoff, attempt history, dead-letter queue and replay, idempotency keys, circuit breaker, rate limits, operation deadline |
| 7 | Audit log, optimistic concurrency (ETag / If-Match), source-of-truth policies, reconciliation, conflicts and resolution |

Documentation status: `README.md` and `PROJECT_STATUS.md` in the repository match this
state (Phase 7 complete) after the Phase 7 Part 4 commit; no correction was needed. The
`frontend/` directory contained only `.gitkeep`: Phase 8 starts from an empty frontend.

## 2. Backend architecture relevant to the frontend

- **Base path** `/api/v1`; organization resources under `/api/v1/organizations/{org}`.
- **Auth**: `POST /auth/login` returns `{access_token, token_type, expires_in}` (JWT,
  30 minutes, no refresh token); `Authorization: Bearer`; `POST /auth/logout` revokes the
  token server-side; `GET /auth/me` returns the user and their memberships with roles.
- **Errors**: always `{"error": {"code", "message", "details", "request_id"}}`; every
  response has `X-Request-ID`.
- **Pagination**: `limit` (1-100) and `offset`; responses `{items, total, limit, offset}`.
- **Concurrency**: employee responses carry `version` and `ETag`; writes accept `If-Match`
  -> `412 version_conflict`.
- **Idempotency**: `POST .../employees` accepts `Idempotency-Key`.
- **CORS**: the API allows `http://localhost:4200`. The frontend nevertheless calls a
  **same-origin** `/api` path - through the Angular dev-server proxy in development, and
  through the reverse proxy in deployment (Phase 10). Same-origin means no CORS
  preflights and lets the browser read `ETag` and `X-Request-ID`, which the API does not
  list in `Access-Control-Expose-Headers`. No backend change is needed.

## 3. API inventory (53 operations)

| Area | Operations |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` |
| Organizations | `GET /organizations` (each with `my_role`), `POST /organizations`, `GET /organizations/{id}`, `PATCH /organizations/{id}` (rename) |
| Members | `GET`, `POST .../members`; `PATCH`, `DELETE .../members/{user_id}` |
| Departments | `GET`, `POST .../departments`; `PATCH` (rename), `DELETE .../departments/{id}` (refused while in use) |
| Employees | `GET .../employees` (search, department, manager, status, location, joined range, include_archived, sort), `POST`, `GET/PATCH/DELETE .../employees/{id}`, `POST .../terminate` |
| Connector catalog | `GET /connector-types` (display name, version, auth type, **simulated**, operations, config and credential JSON schemas) |
| Connectors | `GET`, `POST .../connectors`; `GET`, `PATCH .../connectors/{id}`; `POST .../test`, `.../disconnect`, `.../operations`, `.../reconcile`; `GET .../accounts` |
| Workflows | `GET .../workflows` (trigger, active), `POST`; `GET`, `PATCH .../workflows/{id}`; `POST .../activate`, `.../deactivate`; `GET .../executions` (status) |
| Events | `GET .../events` (status, type, employee), `GET .../events/{id}` (executions, jobs), `GET .../events/{id}/attempts` |
| Dead-letter queue | `GET .../dead-letter-events` (status, connector), `GET .../{id}` (event + history), `POST .../{id}/replay` |
| Data integrity | `GET .../data-source-policies`, `PUT .../data-source-policies/{field}`, `GET .../conflicts` (status, severity, field, employee, connector), `GET .../conflicts/{id}` (resolutions), `POST .../conflicts/{id}/resolve` |
| Audit | `GET .../audit-logs` (action or prefix, resource, actor, outcome, since, until) |
| Probes | `GET /health`, `GET /ready` |

## 4. Entities shown on screens

Organization, membership, user, department, employee (with department and manager refs,
`version`), connector type, connector (status, circuit, credential fingerprint, last
error, simulated), external account, workflow (+ steps), execution (+ jobs), event,
attempt, dead-letter entry, policy, conflict (+ resolutions), audit entry.

## 5. Authentication flow

1. Login form -> `POST /auth/login` -> access token and `expires_in`.
2. `GET /auth/me` -> user, Super Admin flag, memberships (organization + role).
3. The user lands in their organization (`/o/{org}/dashboard`); with several memberships
   the last one used is remembered; with none, the "create organization" screen.
4. Every API call carries the token (interceptor). A `401` with `token_expired`,
   `token_revoked` or `invalid_token` ends the session and returns to the login screen with
   a reason; the URL being visited is restored after login.
5. Logout calls `POST /auth/logout` (server-side revocation), then clears the session.

**Token storage.** The backend issues a bearer token in the response body (no cookie, no
refresh token). The frontend keeps it in memory and mirrors it to `sessionStorage` so a
page reload does not log the user out; `sessionStorage` is per tab and cleared when the tab
closes. This is **not** XSS protection - script running in the page can read it, as it
could read an in-memory token. The mitigations are the ones that actually matter: Angular's
template escaping, no `innerHTML` with untrusted data, no third-party scripts, a short token
lifetime (30 min) and server-side revocation on logout. An HttpOnly-cookie session would
need backend changes and is noted for Phase 9.

## 6. Role and permission matrix (mirrors `ROLE_PERMISSIONS`)

| Permission | Viewer | Integration Manager | Org Admin |
|---|---|---|---|
| `org:read`, `members:read`, `employees:read`, `departments:read`, `connectors:read`, `workflows:read`, `events:read`, `conflicts:read` | yes | yes | yes |
| `connectors:manage`, `workflows:manage`, `events:replay`, `audit:read`, `conflicts:resolve` | - | yes | yes |
| `org:update`, `members:manage`, `employees:write`, `departments:manage`, `policies:manage` | - | - | yes |

Super Admins hold every permission. The frontend copy of this matrix only decides what to
**show**; the backend remains the authority, and a `403` from the API is always handled.

## 7. Screen inventory and screen-to-API mapping

| Screen | Backend endpoints | Permission | Supported actions |
|---|---|---|---|
| Login | `POST /auth/login`, `GET /auth/me` | public | sign in |
| Register | `POST /auth/register` | public | create account (no invitations: unsupported) |
| Create organization | `POST /organizations` | authenticated | create (creator becomes Org Admin) |
| Dashboard | totals from `employees`, `connectors`, `events` (per status), `dead-letter-events`, `conflicts` (per severity), `departments`; daily windows of `audit-logs` (`workflow.executed`, `sync.retry_scheduled`); recent `events`, `audit-logs` | `org:read` (+ `audit:read` for audit-based widgets) | navigate to details |
| Employee directory | `GET .../employees`, `GET .../departments` | `employees:read` | search, filter, sort, paginate; create, edit, terminate, archive (`employees:write`) |
| Employee details | `GET .../employees/{id}`, `GET .../employees?manager_id=`, `GET .../events?employee_id=`, `GET .../conflicts?employee_id=`, `GET .../audit-logs?resource_type=employee&resource_id=` | `employees:read` (+ `audit:read` for history) | edit (If-Match), terminate, archive |
| Departments | `GET/POST .../departments`, `PATCH/DELETE .../{id}` | `departments:read` / `:manage` | create, rename, delete (refused while in use) |
| Reporting structure | `GET .../employees` read page by page (100 per request, up to 1,000 people) and grouped by `manager`; the employee page shows the chain above a person (`GET .../employees/{id}` per level) and direct reports (`?manager_id=`) | `employees:read` | expand / collapse teams, open a person |
| Connector Center | `GET /connector-types`, `GET .../connectors` | `connectors:read` | create (`connectors:manage`) |
| Connector details | `GET .../connectors/{id}`, `GET .../accounts`, `GET .../dead-letter-events?connector_id=`, `GET .../conflicts?connector_id=` | `connectors:read` | test, rename/config, rotate credentials, disconnect, reconcile (`connectors:manage` / `conflicts:resolve`) |
| Event monitor | `GET .../events` | `events:read` | filter by status, type, employee; paginate |
| Event details | `GET .../events/{id}`, `GET .../events/{id}/attempts` | `events:read` | inspect timeline, executions, jobs, attempts |
| Workflow Center | `GET .../workflows` | `workflows:read` | filter; create (`workflows:manage`) |
| Workflow details / builder | `GET .../workflows/{id}`, `GET .../executions`, `GET .../connectors`, `POST/PATCH .../workflows`, `.../activate`, `.../deactivate` | `workflows:read` / `:manage` | step-based builder (trigger + ordered connector operations), activate, deactivate, execution history |
| Reliability Center | `GET .../connectors` (circuit, status, `rate_limit_per_minute`), totals of `events?event_status=retrying`, `dead-letter-events?entry_status=open`, `audit-logs?action=sync.retry_scheduled` | `events:read` (+ `audit:read`) | navigate to DLQ, connectors, events |
| Dead-letter queue | `GET .../dead-letter-events`, `GET .../{id}`, `POST .../{id}/replay` | `events:read` / `events:replay` | inspect, replay (confirmation) |
| Conflicts | `GET .../conflicts`, `GET .../{id}`, `POST .../{id}/resolve`, `GET/PUT .../data-source-policies` | `conflicts:read` / `:resolve` / `policies:manage` | side-by-side compare, resolve (`use_syncforge`, `use_external`, `dismiss` with override and note), configure policies |
| Audit log | `GET .../audit-logs` | `audit:read` | filter by action, resource, actor, outcome, date range; detail drawer |
| Team and roles | `GET/POST .../members`, `PATCH/DELETE .../members/{user_id}` | `members:read` / `:manage` | add registered users, change roles, remove (last-admin rule enforced by the API) |
| Settings | `GET/PATCH /organizations/{id}`, `GET /auth/me` | `org:read` / `org:update` | rename organization, view profile, theme |

### Unsupported - not built as if they worked

| Requested | Why |
|---|---|
| Notifications area | No notification endpoint; omitted from the top bar |
| Invitations for unregistered people | Not implemented in the backend (members must register first) |
| Event date-range filter | `GET .../events` has no date parameters; event filters are status, type, employee |
| Per-employee linked accounts | Accounts are listed per connector only (`.../connectors/{id}/accounts`, no employee filter); shown on connector pages |
| Arbitrary time series for events or employees | No aggregate endpoints. Daily trends use **audit-log windows** (`since`/`until` totals of `workflow.executed` and `sync.retry_scheduled`), which are real history; event charts show current status distributions |
| Workflow drag-and-drop canvas | Workflows are an ordered list of steps (`StepInput`); the builder is a step list with reordering, matching the schema |
| Global search across all entities | Only employees have a search parameter; the top-bar search searches employees |
| Profile editing, password change | No endpoints |
| Deleting connectors or workflows | No endpoints (disconnect / deactivate instead) |

## 8. Component architecture

```
frontend/src/app/
  core/            api (generated types, ApiClient, domain services), auth (session, guards,
                   interceptors), organization context, permissions, theme, toasts
  shared/ui/       design system: button, card, metric card, badge, table, pagination,
                   skeleton, empty/error state, dialog, confirm, drawer, tabs, icon,
                   form field, page header, chart, timeline, JSON/ID displays
  layout/          application shell, sidebar, top bar, breadcrumbs, organization switcher
  features/        auth, dashboard, employees, departments, organization (reporting),
                   connectors, events, workflows, reliability, dead-letters, conflicts,
                   audit, team, settings, onboarding (create organization)
```

- Standalone components, `ChangeDetectionStrategy.OnPush`, zoneless change detection
  (Angular 22 default), lazy-loaded feature routes.
- Presentation components receive data through inputs; pages own data loading through
  domain API services. No component talks to `HttpClient` directly.

## 9. State management

- **Signals** for local and shared state (session, organization, theme, filters).
- **`httpResource`** (stable in Angular 22) for reads: loading / error / value signals,
  automatic cancellation of superseded requests when filters change (no stale overwrite).
- **RxJS** (`HttpClient` observables) for writes and for parallel dashboard queries.
- **URL as state** for filters and pagination (query parameters), so views are shareable
  and survive reloads.
- No NgRx: the application's state is server state plus a few signals.

## 10. Routing

```
/login, /register                          public
/organizations/new                         authenticated, no organization needed
/o/:orgId/dashboard                        organization guard (membership) + permission data
/o/:orgId/employees, /employees/:id
/o/:orgId/departments, /reporting
/o/:orgId/connectors, /connectors/:id
/o/:orgId/events, /events/:id
/o/:orgId/workflows, /workflows/new, /workflows/:id
/o/:orgId/reliability, /dead-letters, /dead-letters/:id
/o/:orgId/conflicts, /conflicts/:id, /policies
/o/:orgId/audit, /team, /settings
```

The organization is part of the URL: links are shareable, reloads keep context, and the
guard verifies membership through the API (`404` -> "not a member" page).

## 11. Design system

Dark-first with a full light theme, implemented as CSS custom properties (design tokens)
on `:root[data-theme]`; components use only tokens. Indigo/violet accent, emerald
success, amber warning, refined red danger. Inter (variable) for text, JetBrains Mono for
IDs and technical values, both self-hosted (`@fontsource-variable`). Icons: a small
`<sf-icon>` component rendering a curated subset of Lucide icons (ISC license) as inline
SVG - the `lucide-angular` package does not yet support Angular 22.

## 12. Charts

Apache ECharts 6 through `ngx-echarts` 22 (supports Angular 22), wrapped in one
`<sf-bar-chart>` component that applies the theme tokens, handles loading / empty / error
states and resizes with its container. Charts only show real data:

| Chart | Data source |
|---|---|
| Workflow execution outcomes per day (last 7 days) | `audit-logs` totals per day for `workflow.executed`, success vs failure |
| Retry activity per day | `audit-logs` totals per day for `sync.retry_scheduled` |
| Event status distribution | `events` totals per status |
| Connector health | `connectors`: status and circuit state |
| Open conflicts by severity | `conflicts` totals per severity |
| Dead-letter entries by error category | `dead-letter-events?entry_status=open` (current page) |
| Department employee distribution | `departments` (`employee_count`) |
| Employment status distribution | `employees` totals per status |

*As built (milestone 4):* the dashboard draws four charts — workflow executions per day,
retries per day, events by status, employees by department. Connector health, conflicts by
severity and employment status are shown as tables and figures rather than charts;
dead-letter categories appear on the dead-letter screens. See
[PHASE_8_FRONTEND_COMPONENTS.md](PHASE_8_FRONTEND_COMPONENTS.md).

## 13. Error handling

One `ApiError` type built by an interceptor from the error envelope (status, code,
message, details, request ID). Pages show inline error states with a retry action and the
request ID (copyable); actions show toasts. Specific handling: `401` session end, `403`
"not permitted" view, `404` not-found view, `409` / `412` conflict messages (412 offers
reload), `422` field-level form errors, `502` connector errors with the normalized
category, `503` service unavailable. Errors are never swallowed.

## 14. Testing

Vitest (Angular 22 default) with TestBed: interceptors, session, guards, the permission
matrix, API services (`HttpTestingController`), form validation, key page components,
theme switching. `npm run api:check` regenerates the API types from the committed OpenAPI
snapshot and fails if they drifted. ESLint with angular-eslint (including template accessibility rules).
Production build with budgets. End-to-end checks against the running backend in Milestone
9 (Playwright, already available in the workspace).

## 15. Milestones

1. Audit and plan (this document); design tokens.
2. Angular foundation: workspace, generated API types, HTTP layer, routing, shell, theme,
   design system.
3. Authentication: login, register, session lifecycle, guards, organization context,
   permissions.
4. Dashboard.
5. Workforce: employees, employee details, departments, reporting structure.
6. Integrations and events: connectors, connector details, event monitor and details.
7. Workflows and reliability: workflow center, builder, executions, reliability center, DLQ.
8. Data integrity and governance: conflicts, policies, audit log, team, settings.
9. Integration and QA: end-to-end checks against the backend, permissions, responsive, build.
10. Polish and documentation: the Phase 8 documents, README, PROJECT_STATUS, CHANGELOG.

## 16. Known backend limitations affecting the UI

- No aggregate or time-series endpoints (section 12 explains what is used instead).
- Lists cap `limit` at 100; the dashboard uses `limit=1` queries to read totals.
- Lists of events, dead letters and conflicts return employee **IDs**, not names; names are
  looked up per row through a small cache (one request per distinct employee).
- No refresh tokens: after 30 minutes the user signs in again (the UI warns before expiry).
- Event filters have no date range; the audit log does.
