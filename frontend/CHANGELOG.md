# Changelog

All notable changes to SyncForge are recorded here.

## [Unreleased]

### Phase 8 - Angular frontend (complete)

#### Added
- `docs/PHASE_8_FRONTEND_PLAN.md`: repository audit, API inventory, permission matrix,
  screen-to-endpoint map, unsupported features, architecture and milestones.
- `frontend/`: Angular 22 application (standalone components, OnPush, zoneless, strict
  templates) with API types generated from the backend's OpenAPI document, typed API
  services, an error interceptor producing one `ApiError` type, and a dev-server proxy.
- Design system: design tokens with a dark default and a light theme, self-hosted Inter and
  JetBrains Mono, Lucide icons, shell with organization switcher, and shared components.
- Sign-in, registration and organization creation; session restore per tab, server-side
  logout, return to the requested page after a 401, guards for organization membership
  and permissions.
- Dashboard computed only from existing endpoints, with daily history from the audit log.
- Workforce screens: employee directory with URL-based filters, add and edit dialogs
  (changed fields only, `If-Match`, `Idempotency-Key`, recovery from `412`), employee page
  with reporting line, direct reports, sync events, conflicts and change history,
  termination and archiving, departments, reporting-lines tree, top-bar employee search.
- Connector screens: catalog and list, forms generated from each connector type's JSON
  schema (create, settings, credential replacement), connection test, manual operation,
  reconcile, disconnect, and per-connector linked accounts, dead letters, conflicts and
  history.
- Event monitor and event page: filters in the URL, optional auto-refresh, timeline,
  workflow executions with per-step results, and the full attempt history.
- Workflow screens: list, step builder (create and edit, new version on change),
  workflow page with activation and execution history.
- Reliability overview and dead-letter queue with entry pages and replay.
- Governance screens: data conflicts with side-by-side comparison and resolution,
  source-of-truth policies, audit log with filters and details, team and roles, settings.
- Collapsible sidebar: an icons-only rail on wide screens (labels as tooltips), remembered
  in the browser; on narrow screens the sidebar stays a slide-in drawer.
- Password fields: show / hide button (accessible label and pressed state), Caps Lock
  notice, and a length-based strength hint at registration.
- Browser test suite (`frontend/e2e/`, Playwright 1.65.0, `npm run e2e`): 13 tests against
  the real API, worker, relay and mock services, each on a freshly provisioned tenant, plus
  axe accessibility checks (14 pages, both themes) and a 390 px phone layout check.
  Results in `docs/PHASE_8_FRONTEND_TESTING.md`.
- Frontend documentation: `docs/PHASE_8_FRONTEND_ARCHITECTURE.md`, `_COMPONENTS.md`,
  `_API_INTEGRATION.md`, `_REPORT.md`; ADR-0020 (signals and server state, generated API
  types); README screenshots (`docs/screenshots/`) and instructions for running the web
  application.

#### Changed
- Conflict history shows readable decisions ("Kept SyncForge's value", "Used the
  application's value", "Dismissed") instead of the API's raw values.
- Colour tokens raised to WCAG AA contrast in both themes; danger buttons use a new solid
  danger colour.
- Every data table scrolls inside its own container, so pages fit a 390 px phone screen.
- The "Main navigation" label moved from the sidebar `<aside>` to its `<nav>`.
- Minimum password length lowered from 12 to 8 characters (backend `PASSWORD_MIN_LENGTH`,
  the `create-superadmin` prompt, the registration form, docs/08 and docs/15), at the
  project owner's request. No composition rules; 128-character maximum unchanged.
- When the API cannot be reached (connection refused, or a 502/503/504 from the dev-server
  proxy with no SyncForge error body), screens now say the API is not responding instead
  of showing "502 Bad Gateway".

### Phase 7 - Data integrity, conflict resolution and audit logging (complete)

#### Added
- Audit log (`audit_logs`, migration `0010`): actor (user or system), action, resource,
  outcome, details, request ID; written in the same transaction as each change for
  employees, departments, organization, memberships (permission changes), connectors
  (including manual operations and reconciliation), workflows, dead-letter replays,
  workflow executions, scheduled retries, dead letters, circuit-breaker transitions,
  conflicts and policies. No secrets; personal values only as field names. A trigger makes
  the table append-only (UPDATE refused except the actor's ON DELETE SET NULL; DELETE only
  with an explicit retention switch).
- `GET .../audit-logs` with filters (action or action prefix, resource, actor, outcome,
  time range); permission `audit:read` (Organization Admin, Integration Manager).
- Optimistic concurrency for employees: `version` column (migration `0011`), `ETag` on
  responses, `If-Match` on PATCH, terminate and archive, `412 version_conflict`; row lock +
  `WHERE version = ...` make the check atomic.
- Data integrity (migration `0012`): `data_source_policies` (per field: SyncForge or one
  connector authoritative, severity, manual/auto), `data_conflicts` (one open per
  employee, connector and field), `conflict_resolutions` (history).
- `POST .../connectors/{id}/reconcile`: reads linked accounts and records differences as
  conflicts (never overwrites); self-closing when values agree again; automatic resolution
  where the policy says so; a terminated person with an active account is always critical.
- Conflict API: list, detail with history, resolve (`use_syncforge`, `use_external`,
  `dismiss`) with override + note for decisions against the policy, staleness checks,
  `employees:write` for adopting values; policies API (`GET`, `PUT` by Organization Admins).
- Permissions `conflicts:read` (all), `conflicts:resolve` (Integration Manager, Admin),
  `policies:manage` (Admin).
- Connectors return department, designation and location from the applications;
  `ConnectorService.read_external_user`.
- Demo scenarios 6 (data conflict) and 7 (concurrent edits and the audit trail).
- 59 new tests (526 total), including a two-session test for simultaneous saves.
- Documentation: data integrity (docs/14, new), ADR-0017 (audit log), ADR-0018 (optimistic
  concurrency), ADR-0019 (source of truth and reconciliation); architecture, database, API,
  connector, reliability, security, troubleshooting and README updated.

#### Changed
- Employee responses include `version` and an `ETag` header.
- Integration Managers can read the audit log and resolve conflicts.

### Phase 6 - Reliability engine and failure recovery (complete)

#### Added
- Retries: `RetryPolicy` with exponential backoff (2, 4, 8, ... s), proportional jitter
  (+/-20 %), `Retry-After` honoured (never earlier, capped) and a bounded number of attempts
  (default 5, first included); only `server`, `timeout`, `network`, `rate_limited`,
  `in_progress` and `circuit_open` failures are retried. Settings `RETRY_MAX_ATTEMPTS`,
  `RETRY_BASE_DELAY_SECONDS`, `RETRY_MAX_DELAY_SECONDS`, `RETRY_JITTER_RATIO`.
- `retrying` status for events and jobs with `next_attempt_at`; the outbox relay dispatches
  due retries; later steps of an execution wait (migration `0006`).
- `synchronization_attempts`: one row per external call, opened before and closed after
  it; open attempts are closed as `interrupted` on resume. `GET .../events/{id}/attempts`.
- Dead-letter queue: events that fail for good end in `dead_letter` with a
  `dead_letter_events` entry that copies the error (reason `retries_exhausted` or
  `non_retryable`); `GET .../dead-letter-events` (filters `entry_status`, `connector_id`),
  `GET .../dead-letter-events/{id}` (with the event and every round),
  `POST .../dead-letter-events/{id}/replay` (`202`) (migration `0007`).
- Replay resets only failed steps and those skipped because of them, gives each a fresh
  retry budget (`attempts_at_last_replay`), and requeues the event through the outbox in
  one transaction; row locks make simultaneous replays safe; `409 already_replayed`,
  `409 workflow_inactive`.
- Permission `events:replay` (Integration Manager, Organization Admin).
- Outgoing idempotency keys: `Idempotency-Key: syncforge-job-<job id>` on `create_user`,
  identical across attempts and replays. The mock services honour the header (stored
  response with `Idempotent-Replayed: true`, `422` on key reuse, `409
  idempotency_key_in_use` while running); new retryable category `in_progress`. A mock
  timeout fault now still executes the request after the delay.
- Incoming idempotency: optional `Idempotency-Key` on `POST .../employees`; the response is
  stored in `idempotency_records` in the same transaction as the employee; same key and body
  replays it, a different body is `422 idempotency_key_reused`; keys scoped per user;
  setting `IDEMPOTENCY_TTL_HOURS` (migration `0008`).
- Circuit breaker per connector, state shared in `connector_circuits` (closed / open /
  half-open with one trial call); refused calls fail with retryable `circuit_open`; a
  successful connection test closes it; connector responses include `circuit`. Settings
  `CIRCUIT_FAILURE_THRESHOLD`, `CIRCUIT_OPEN_SECONDS` (migration `0009`).
- Per-connector rate limit: optional `rate_limit_per_minute` in connector config, counted
  per minute in `connector_rate_windows` across all workers; jobs over the limit are
  deferred to the next minute without using an attempt (job `error_category` `throttled`).
- Operation deadline: `CONNECTOR_OPERATION_TIMEOUT_SECONDS` (default 30) caps one
  operation across all of its requests; past it, `operation_timeout` (retryable).
- `python -m app.cli purge-expired`: deletes expired revoked tokens and idempotency records.
- `infrastructure/scripts/demo_reliability.py`: five live failure scenarios against a
  running stack.
- 71 new tests (467 total), including two-session concurrency tests for a due retry
  claimed while the relay holds the row and for simultaneous replays.
- Documentation: reliability and retries (docs/12, new), idempotency (docs/13, new),
  ADR-0013 (retries), ADR-0014 (dead-letter queue and replay), ADR-0015 (idempotency keys),
  ADR-0016 (circuit breaker and rate limits); architecture, database, API, events,
  connector, workflow engine, security, troubleshooting and README updated.

#### Changed
- Event status `failed` is replaced by `dead_letter`; migration `0007` moves existing failed
  events into the queue with entries built from their first failed step.
- A step that fails with a retryable error is retried instead of failing the event.
- `create_user` on connectors accepts an optional `idempotency_key`.

#### Fixed
- A worker could skip a due retry when it received the message before the relay committed
  `pending` (READ COMMITTED); due `retrying` events are now claimable (found in the live
  retry run, covered by a concurrency test).

### Phase 5 - Workflow engine and asynchronous event processing (complete)

#### Added
- Alembic migration `0005`: `workflows`, `workflow_steps`, `integration_events`,
  `outbox_events`, `workflow_executions`, `synchronization_jobs`, with composite
  same-organization foreign keys.
- Transactional outbox: employee changes write their integration events and outbox rows in
  the same transaction; the request ID is stored as the event's correlation ID; the
  lifecycle log line now carries the event ID.
- Workflow API: create, list (filters), get, update (versioned), activate, deactivate,
  execution history. Events API: list (status, type, employee filters) and detail with
  executions and per-step jobs; changed field names only, never values.
- Permissions `workflows:read`, `events:read` (all members) and `workflows:manage`
  (Integration Manager, Organization Admin).
- Workflow engine: atomic claim with a worker lease, one execution per event and workflow,
  sequential steps through `ConnectorService`, resume without repeating finished steps,
  `skipped` vs `failed` job outcomes, current-state processing.
- Outbox relay (`python -m app.cli outbox-relay`): ordered publishing with
  `FOR UPDATE SKIP LOCKED`, broker-outage tolerance, re-dispatch of events whose lease
  expired.
- Celery worker (`app/workers/`) with late acknowledgement, reject on worker loss,
  prefetch 1, JSON-only messages and structured JSON logs.
- Redis 7 in Docker Compose (no persistence; the database is the source of truth).
- `python -m mockservices.run_all` starts all three mock services in one process.
- Settings `REDIS_URL`, `WORKER_LEASE_SECONDS`, `OUTBOX_BATCH_SIZE`,
  `OUTBOX_POLL_INTERVAL_SECONDS`.
- Dependencies: `celery` 5.7.0, `redis` 8.1.0.
- 64 new tests (396 total), including a real Celery worker with an in-memory broker,
  duplicate delivery and crash recovery.
- Documentation: event-driven architecture (docs/09, new), workflow engine (docs/11, new),
  ADR-0010 (Redis and Celery), ADR-0011 (asynchronous processing, at-least-once),
  ADR-0012 (transactional outbox); architecture, components, database, API, security,
  troubleshooting and mock-services README updated.

#### Changed
- Lifecycle events are no longer only logged after the commit: they are stored durably in
  the same transaction (closes the Phase 3 gap where a crash between commit and log could
  lose an event).

#### Fixed
- Outbox relay recovery renewed the lease of an abandoned `processing` event, so the next
  worker skipped it indefinitely; recovered events are now reset to `pending` (found in the
  live crash demonstration, covered by a new test).
- The `workflow_steps` -> `connectors` foreign key is checked at commit, so deleting an
  organization is not refused by the order of its cascades.

#### Removed
- Empty `.gitkeep` placeholders in folders that now contain code.

### Phase 4 - Connector framework and external application integrations (complete)

#### Added
- Connector framework: `Connector` interface (`test_connection`, `create_user`,
  `update_user`, `deactivate_user`, `get_user`), `ConnectorSpec` metadata, registry with
  `@register`, semantic versioning with major-version refusal.
- `ConnectorHttpClient`: connect/read timeouts, host allowlist (SSRF), no redirects, no
  environment proxies, latency measurement, no body logging.
- Error normalization into categories (authentication, authorization, validation,
  not_found, conflict, rate_limited, timeout, network, server, permanent, configuration)
  with a `retryable` flag and `Retry-After` parsing (seconds or HTTP date, capped).
- Adapters (simulated): Slack SCIM v2 (bearer token), Google Workspace Directory API
  (OAuth 2.0 token exchange, caching, refresh-on-401), payroll REST API (API key).
- Fernet encryption of connector credentials with comma-separated key rotation;
  4-character fingerprints; blank key treated as not configured.
- Alembic migration `0004`: `connectors`, `connector_credentials`, `external_accounts`
  with composite same-organization foreign keys.
- Connector API: catalog, list, create, get, update/rotate, test, disconnect, operations,
  linked accounts; `502 connector_error` with normalized details.
- Permissions `connectors:read` (all members) and `connectors:manage` (Integration
  Manager, Organization Admin).
- Mock Slack, Google Workspace and payroll services (`mock-services/mockservices/`) with
  a shared failure-injection control API and Google token expiry.
- Dependencies: `cryptography` 50.0.2, `httpx2` 2.16.0 (runtime); `python-multipart`
  0.0.33 (mock services).
- 124 new tests (332 total), including adapter and API tests over real HTTP.
- Documentation: connector framework (new), mock-services README, database, API,
  security, architecture and component design; ADR-0008 (adapter pattern), ADR-0009
  (credential encryption); troubleshooting guide (`docs/21-troubleshooting.md`).

#### Changed
- The empty `mock-services/slack-mock`, `google-workspace-mock` and `payroll-mock`
  folders were replaced by one importable package, `mock-services/mockservices/`.
- Integration Managers gained `connectors:manage`.

#### Fixed
- Mock endpoint defaults use `127.0.0.1` instead of `localhost` (on Windows, `localhost`
  tried IPv6 first and added ~2 s to every connector call).
- `test_unreachable_service_is_a_network_error` failed on Windows, where refused loopback
  connections are retried ~2 s; it now uses a 5 s connect timeout.

### Phase 3 - Employee management and workforce data model (complete)

#### Added
- Alembic migration `0003`: `departments` (case-insensitive unique names per organization)
  and `employees` with composite foreign keys that keep department and manager in the same
  organization, check constraints for lifecycle consistency, and organization-scoped indexes.
- Departments API: list with employee counts, create, rename, delete (`409 department_in_use`).
- Employees API: create, get, list with search / filters / sorting / stable pagination,
  partial update, terminate (direct reports move up), archive (soft delete).
- Business rules: same-organization references, no terminated managers, no reporting-line
  cycles (recursive query), terminated employees are read-only.
- Per-organization advisory lock serializing manager changes; two-session concurrency test.
- Lifecycle event detection (`employee.created`, `.updated`, `.department_changed`,
  `.manager_changed`, `.terminated`) as pure functions; events logged with IDs and field
  names only.
- Permissions `employees:read`, `employees:write`, `departments:read`, `departments:manage`.
- `UnprocessableError` (422) for business-rule violations in well-formed input.
- `python -m app.cli seed-demo` demo data command.
- 97 new tests (208 total).
- Documentation: component design (new), database design, API design, security design,
  system architecture; ADR-0006 (composite foreign keys), ADR-0007 (advisory lock).

### Phase 2 - Backend foundation, authentication and organizations (complete)

#### Added
- Docker Compose service for PostgreSQL 16 with health check and persistent volume.
- FastAPI application factory with pinned dependencies (`requirements.txt`, `requirements-dev.txt`).
- Settings via pydantic-settings; refuses placeholder secrets in production.
- Structured JSON logging; `X-Request-ID` on every response; per-request timing log.
- Standard error envelope for application, HTTP, validation and unexpected errors.
- `GET /health` (liveness) and `GET /ready` (database readiness).
- SQLAlchemy models and Alembic migration `0001`: `organizations`, `users`,
  `organization_memberships` with named constraints and indexes.
- Argon2id password hashing and HS256 JWT access tokens.
- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`,
  `POST /api/v1/auth/logout`.
- Alembic migration `0002`: `revoked_tokens` logout denylist.
- 55 automated tests (health, migrations, DB constraints, security, auth API).
- Documentation: system architecture, database design, API design, security design,
  ADR-0001 to ADR-0004.
- Organizations API: create, list (paginated), get, rename.
- Membership API: list, add by email, change role, remove.
- Role-based permissions (`org:read`, `org:update`, `members:read`, `members:manage`) and
  organization isolation: non-members get 404, members without permission get 403.
- "At least one Organization Admin" rule protected by `SELECT ... FOR UPDATE` row locks.
- `python -m app.cli create-superadmin` operator command.
- Shared pagination schema (`items`, `total`, `limit`, `offset`).
- 56 new tests (111 total), including a two-session concurrency test.
- ADR-0005: organization-level data isolation.

#### Verified
- Clean clone from GitHub following the README: migrations applied from an empty
  database, no model/migration drift, 111 tests passing.

### Phase 1 - Development environment and repository setup
- Initialized Git repository on `main` with project folder structure.
- Added README, PROJECT_PLAN, PROJECT_STATUS, .gitignore, .gitattributes, .editorconfig, .env.example.
