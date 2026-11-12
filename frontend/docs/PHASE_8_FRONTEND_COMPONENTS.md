# Phase 8 — Frontend components

Inventory of the Angular components and helpers in `frontend/src/app`, what each one is
responsible for, and the API calls behind each screen. Architecture:
[PHASE_8_FRONTEND_ARCHITECTURE.md](PHASE_8_FRONTEND_ARCHITECTURE.md).

All components are standalone and use `ChangeDetectionStrategy.OnPush`. Component
selectors use the `sf-` prefix.

## 1. Shared UI (`shared/ui`, `shared/charts`)

Presentational components. They receive data through inputs and report through outputs
or two-way `model()` bindings; none of them calls the API.

| Selector | Inputs / outputs | Purpose |
|---|---|---|
| `sf-page-header` | `title`, `description`, `crumbs`; projected actions | Page title, breadcrumbs, primary actions |
| `sf-metric` | `label`, `value`, `hint`, `icon`, `tone`, `link`, `error` | Dashboard and overview figures; shows "unavailable" when its own request failed |
| `sf-badge` | `tone`, `dot` | Coloured label |
| `sf-status` | `value`, `label` | Badge whose colour comes from a status value (`statusTone()`), always with text |
| `sf-empty-state` | `icon`, `title`, `message`; projected action | Empty list with the next step |
| `sf-error-state` | `error`, `(retry)` | Failed load: message, copyable request ID, Retry |
| `sf-skeleton` | `rows`, `height` | Loading placeholder |
| `sf-pagination` | `total`, `limit`, `offset`, `(offsetChange)` | Offset paging matching the API's `limit`/`offset` |
| `sf-tabs` | `tabs`, `[(active)]` | Accessible tab list (arrow keys, `aria-selected`) |
| `sf-dialog` | `title`, `description`; projected body and footer | Frame for every dialog and drawer |
| `sf-confirm-dialog` | opened through `DialogService.confirm()` | Confirmation, optionally "type the name to confirm" for destructive actions |
| `sf-password-field` | form control | Password input with show/hide toggle and Caps Lock notice |
| `sf-employee-picker` | `[(value)]`, `excludeId`, `includeTerminated`, `emptyText`, `inputId` | Searchable employee selector (manager field, filters) backed by the employee search API |
| `sf-employee-name` | `id`, `link` | Resolves an employee ID to a name through the shared cache |
| `sf-id` | `value`, `short` | Shortened ID with copy button |
| `sf-time` | `value`, `absoluteOnly` | Relative time with the exact timestamp in a tooltip and `<time>` |
| `sf-json` | `value` | Readable JSON for event payloads and audit details |
| `sf-icon` | `name`, `size`, `strokeWidth` | Inline SVG from a curated Lucide subset (`aria-hidden`) |
| `sf-toast-outlet` | — | Renders toasts from `ToastService` in a polite live region |
| `sf-bar-chart` | `categories`, `series`, `stacked`, `horizontal`, `height`, `categoryLabel`, `summary` | ECharts bar chart themed from tokens, with a visually hidden data table for screen readers |

Services and helpers:

| Name | Purpose |
|---|---|
| `DialogService` | `open()`, `drawer()`, `confirm()` over the Angular CDK dialog |
| `useQueryState()` | Read and update list filters in the URL query string |
| `useAutoRefresh(reload, seconds)` | Optional polling while the tab is visible |
| `applyServerErrors()`, `controlError()`, `safeReturnUrl()` | Map 422 field errors onto forms, standard field messages, reject open redirects |

## 2. Layout (`layout`)

| Component | Responsibility |
|---|---|
| `ShellComponent` (`sf-shell`) | Sidebar (collapsible rail on wide screens, drawer on narrow), top bar with employee search, organization switcher, user menu (theme, settings, sign out), session-expiry warning, router outlet |
| `NAV` (`nav.ts`) | Navigation groups; each entry declares the permission it needs |
| `BrandMarkComponent` | Logo |

## 3. Feature pages

Each row is a lazily loaded route. "API" lists the calls the page makes; the full
method-by-method reference is in [API integration](PHASE_8_FRONTEND_API_INTEGRATION.md).

### Authentication and onboarding

| Component | Route | API | Notes |
|---|---|---|---|
| `LoginComponent` | `/login` | `POST /auth/login`, `GET /auth/me` | Explains why a session ended; honours `returnUrl` (same-origin only) |
| `RegisterComponent` | `/register` | `POST /auth/register`, then login | 8-character minimum, strength hint |
| `CreateOrganizationComponent` | `/organizations/new` | `POST /organizations` | Creator becomes Organization Admin |
| `UnavailableComponent`, `ForbiddenComponent`, `NotFoundComponent` | system pages | — | Explicit states instead of blank screens |

### Overview

| Component | Route | API |
|---|---|---|
| `DashboardComponent` + `DashboardData` | `dashboard` | `limit=1` totals of employees (per status), workflows, events (per status), open dead letters, open conflicts (per severity); connectors; departments; recent events; audit-log totals per day for `workflow.executed` and `sync.retry_scheduled` (7 days); recent audit entries |
| `ConnectorHealthComponent` | part of the dashboard | connectors list (status, circuit) |

Charts on the dashboard: workflow executions per day (success / failure), retries
scheduled per day, events by status, employees by department. Panels built from the
audit log need `audit:read`; viewers see a short explanation in their place.

### Workforce

| Component | Route | API | Notes |
|---|---|---|---|
| `EmployeesListComponent` | `employees` | `GET employees` (search, department, status, location, joining date range, archived, sort, paging), departments | Filters in the URL |
| `EmployeeFormDialogComponent` | dialog | `POST employees` with `Idempotency-Key`; `PATCH employees/{id}` with `If-Match` | Sends only changed fields; 412 offers "Load latest"; 422 errors on fields |
| `TerminateDialogComponent` | dialog | `POST employees/{id}/terminate` with `If-Match` | Typed confirmation |
| `EmployeeDetailComponent` | `employees/:id` | employee, manager chain, direct reports (`manager_id`) | Edit, terminate, archive (`DELETE` with `If-Match`) |
| `EmployeeActivityComponent` | tabs on the employee page | events, conflicts, audit history for the employee | |
| `DepartmentsComponent` | `departments` | departments CRUD | Delete only when empty (API rule) |
| `ReportingComponent` + `reporting-tree.ts` | `reporting` | employees, read page by page | Tree grouped by manager, expand / collapse |

### Integrations

| Component | Route | API | Notes |
|---|---|---|---|
| `ConnectorsListComponent` | `connectors` | `GET /connector-types`, connectors | Catalog with "Simulated" marked on mock-backed types |
| `ConnectorFormDialogComponent` + `SchemaFormComponent` + `schema-fields.ts` | dialog | `POST` / `PATCH connectors` | Form generated from the type's JSON schema; credentials are write-only (only a fingerprint is ever shown) |
| `ConnectorDetailComponent` | `connectors/:id` | connector, test, disconnect, reconcile | Test shows the normalized error category |
| `ConnectorOperationComponent` | tab | `POST connectors/{id}/operations` | Manual create / update / deactivate / get for one employee |
| `ConnectorActivityComponent` | tabs | accounts, dead letters and conflicts for the connector | |
| `WorkflowsListComponent` | `workflows` | workflows (trigger, active filters) | |
| `WorkflowBuilderComponent` | `workflows/new`, `workflows/:id/edit` | connectors, `POST` / `PATCH workflows` | Ordered steps, reorder, duplicate and disconnected-connector warnings, 20-step limit |
| `WorkflowDetailComponent` + `WorkflowStepsComponent` | `workflows/:id` | workflow, activate / deactivate, executions | Activation refusal lists the disconnected connectors |
| `EventsListComponent` | `events` | events (status, type, employee) | Optional 5 s refresh |
| `EventDetailComponent` | `events/:id` | event, attempts | Timeline, executions with per-step results, every attempt with HTTP status, error, duration, next retry; refreshes until settled |

### Reliability

| Component | Route | API |
|---|---|---|
| `ReliabilityComponent` | `reliability` | retrying events, open dead letters, connectors (circuit, rate limit), audit-log counts for retries, dead letters, circuit openings and replays |
| `DeadLettersListComponent` | `dead-letters` | dead letters (status, connector) |
| `DeadLetterDetailComponent` | `dead-letters/:id` | entry, replay (`events:replay`, confirmation), other entries for the same event |

### Governance

| Component | Route | API | Notes |
|---|---|---|---|
| `ConflictsListComponent` | `conflicts` | conflicts (status, severity, field, connector) | |
| `ConflictDetailComponent` + `conflict-fields.ts` | `conflicts/:id` | conflict, resolve | Side-by-side values with the authoritative side marked; choosing against the policy requires override and a note, as the API does; stale conflicts link to reconcile |
| `PoliciesComponent` | `policies` | `GET` / `PUT data-source-policies` | Edit needs `policies:manage` |
| `AuditLogComponent` | `audit` | audit logs (action group, resource, actor, outcome, time range) | Expandable details, links to resources |
| `TeamComponent` | `team` | members list, add, change role, remove | Registered users only; last-admin refusal explained |
| `SettingsComponent` | `settings` | organization rename, `GET /auth/me` | Theme, memberships, session end time, sign out |

## 4. Unit test coverage

| Spec | What it checks |
|---|---|
| `api-error.spec.ts` | Envelope parsing, network errors, proxy 502/503/504 as "API unreachable", field issues |
| `interceptors.spec.ts` | Token added only to API calls; 401 ends the session with `returnUrl` |
| `guards.spec.ts`, `session.service.spec.ts` | Redirects, restore, expiry, logout |
| `permissions.spec.ts` | Role matrix |
| `theme.service.spec.ts`, `format.spec.ts`, `forms.spec.ts` | Theme, formatting, form helpers |
| `dashboard-data.spec.ts` | Totals and per-day windows, independent failures |
| `reporting-tree.spec.ts`, `schema-fields.spec.ts` | Tree grouping, schema-to-form mapping |
| `password-field.component.spec.ts` | Toggle and accessible state |
| `employee-form.dialog.spec.ts` | Changed fields only, `If-Match`, 412 handling |
| `connector-form.dialog.spec.ts` | Schema form, create and edit |
| `workflow-builder.component.spec.ts` | Suggested operation, duplicate refusal, ordered steps |
| `conflict-detail.component.spec.ts` | Override and note rules |

16 files, 57 tests. Browser-level coverage is in the [testing report](PHASE_8_FRONTEND_TESTING.md).
