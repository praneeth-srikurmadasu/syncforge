# SyncForge - Project Status

**Current phase:** 10 in progress - Docker, CI/CD, deployment, final delivery (plan: `docs/PHASE_10_PLAN.md`). Milestones 1-3 delivered.
**Last updated:** 2026-11-12

| Phase | Status |
|---|---|
| 1 - Environment and repository | Complete |
| 2 - Backend foundation, auth, organizations | Complete |
| 3 - Employee management | Complete |
| 4 - Connector framework and mock services | Complete |
| 5 - Workflow engine and event processing | Complete |
| 6 - Reliability engine and failure recovery | Complete |
| 7 - Data integrity, conflicts, audit logging | Complete |
| 8 - Angular frontend | Complete |
| 9 - Security, versioning, observability, QA | Complete |
| 10 - Docker, CI/CD, deployment, final delivery | In progress (milestones 1-3 of 5) |

## Phase 10 progress

| Milestone | Scope | Status |
|---|---|---|
| 1 | Docker: backend image (API, worker, relay, migration job), web image (Angular build served by nginx, which forwards API paths), mock-services image, `.dockerignore` files, Compose profile `full` with health checks and start-up order (`docker compose up -d` unchanged); `packaging` added to runtime requirements (missing dependency found by the container check) | Done |
| 2 | GitHub Actions CI (`.github/workflows/ci.yml`): backend (ruff, migrations + `alembic check`, pytest with PostgreSQL and Redis), frontend (lint, format, API check, unit tests, build, audit), Docker stack with the Playwright browser tests against the containers; no secrets | Done |
| 3 | `docs/17-deployment-guide.md`: local Docker versus production, components, reference architecture, configuration, secrets and key rotation, database (roles, pooling, TLS, backups), releases (expand-and-contract migrations, rollback), probes, logging, production checklist | Done |
| 4 | Remaining documents, `CONTRIBUTING.md`, `LICENSE` | Next |
| 5 | Final delivery | Planned |

### Phase 10 verification (actual results)
- Milestone 1, Windows (owner, commit `f30cf29`): `docker compose --profile full up -d
  --build` built the three images (223 s) and started every service; `api` healthy,
  worker, relay, mocks and web running.
- Milestone 2, Linux workspace: `actionlint` 1.7.12 reports no problems. The backend and
  frontend jobs' steps were run as written from a clean copy without `.env`, with only the
  CI environment variables: ruff clean (backend 173 files, mock services and scripts 9),
  migrations 0001-0016 on an empty database and `alembic check` clean, **579 passed**;
  frontend lint, format, API check, **60 passed**, build, `npm audit --omit=dev` 0. The
  key command produces a valid Fernet key. The stack job (containers + browser tests)
  runs on GitHub; its first result is checked after the push.
- Milestone 1, Linux workspace. Docker Hub is blocked here by network policy, so images
  could not be pulled or built in this workspace. Verified instead: `docker compose config`
  valid with and without `--profile full`, and the rendered environment checked per
  service (container hosts override `.env`, only the API trusts forwarded addresses, the
  API has no published port). Each image's steps were run in clean environments: backend
  runtime requirements only -> `alembic upgrade head` on an empty database (0001-0016);
  API with `--proxy-headers`, worker (`--concurrency=2`), relay and the three mocks from
  those environments; an onboarding hire completed with three successful steps, and a
  login sent with `X-Forwarded-For: 203.0.113.77` was recorded with that address. This
  check found that the worker failed without `packaging` (imported by kombu's Redis
  transport, undeclared); pinned in `backend/requirements.txt`. Frontend `npm ci` and
  `ng build --configuration production` from a clean copy succeeded (351.52 kB initial).
  The container run itself is verified on the owner's Windows machine.

## Phase 9 progress

| Milestone | Scope | Status |
|---|---|---|
| 1 | Audit and plan (`docs/PHASE_9_PLAN.md`) | Done |
| 2 | Sign-in and registration rate limits (PostgreSQL fixed windows, hashed subjects, 429 with Retry-After), common-password refusal (registration and CLI), 1 MiB request body limit (413), security headers, CORS headers for `If-Match` / `Idempotency-Key`; UI shows the reasons | Done |
| 3 | Security events: append-only `security_events` (migration 0014) for sign-ins, failures, sign-outs, registrations and rate-limit refusals (recorded once per window); `GET /auth/activity` (own), `GET /security-events` (Super Admins); "Recent sign-ins" in Settings | Done |
| 4 | Observability: worker and relay heartbeats (migration 0015), `GET /system/status` (Super Admins), `GET .../summary` with processing durations (p50 / p95 / max, 24 h), `event delivery finished` log line with duration; dashboard uses the summary (48 -> 33 requests per load, measured); `docs/18-observability.md` | Done |
| 5 | `/api/v2/organizations/{id}/employees` with keyset (cursor) pagination, opaque validated cursors, v1 unchanged; versioning policy and v1 -> v2 migration guide (docs/08 section 14); ADR-0021 | Done |
| 6 | Performance: `infrastructure/scripts/benchmark.py` (API latency percentiles, event throughput, EXPLAIN ANALYZE), results in `docs/performance/`, `docs/19-performance-and-scalability.md`; employee name index widened to the full sort key (migration 0016) after the measurements showed sorts and a sequential scan | Done |
| 7 | Quality pass: backend suite 5x in order and 3x in random order, browser suite 2x, dependency audits (pip-audit, npm audit), secret scan, security review table (docs/15 section 11) with three new CORS tests, `docs/16-testing-strategy.md`, troubleshooting entries, `docs/PHASE_9_QA_REPORT.md` | Done |

### Phase 9 verification (actual results)
- Milestone 7, Linux workspace: backend 576 passed in 5 consecutive runs and in 3
  random orders, **579 passed** after the CORS tests; ruff clean (backend, mock services);
  frontend **60 passed**, lint, format, API check clean, build success; `npm run e2e`
  **13 passed** twice; pip-audit: no known vulnerabilities; `npm audit --omit=dev`: 0;
  secret scan: test values only. Details: `docs/PHASE_9_QA_REPORT.md`.
- Milestone 6, Linux workspace (2 CPUs, everything on one machine; docs/19): four
  benchmark runs. 1,000 employees: endpoints 9-17 ms p50. 10,000 employees: OFFSET last
  page 27.6 ms vs cursor 9.9 ms, search 38.5 ms, summary 40.2 ms. One worker about 10
  events/s (3 external calls each, about 90 ms worker time per event); two workers 16.3
  events/s. Index change: page 1 0.115 -> 0.032 ms, cursor page 0.073 -> 0.036 ms (no
  sort). Backend `alembic check` clean after migration 0016; migration, v2 and employee
  API tests pass.
- Milestone 5, Linux workspace: backend lint / format clean, `python -m pytest` **576
  passed** (12 new in `tests/test_api_v2.py`, including a hire and an archive between two
  page requests: v2 continued exactly after the last row, v1's offset repeated one);
  frontend build and `api:check` clean. Live: the demo organization's 14 employees walked
  in 3 pages of 5 with no repeats.
- Milestone 4, Linux workspace: backend lint / format clean, `python -m pytest` **564
  passed** (9 new in `tests/test_monitoring.py`, including summary counts equal to the list
  totals); frontend `npm run test:ci` **60 passed**, lint clean, `npm run e2e` **13
  passed**. Live: both heartbeats reported; with the worker stopped for 70 s,
  `system/status` returned `healthy: false` ("No worker has reported in the last 60
  seconds"), and a restarted worker appeared healthy within 20 s. Dashboard load on the
  demo organization: 48 API requests before, 33 after (counted in headless Chrome).
- Milestone 3, Linux workspace: backend lint / format clean, `python -m pytest` **555
  passed** (8 new in `tests/test_security_events.py`; migration checks include 0014);
  frontend `npm run test:ci` **59 passed**, lint clean, `npm run e2e` **13 passed** (axe
  and phone checks include the new Settings card). In headless Chrome, a wrong then a
  correct password showed "Failed sign-in - wrong password" and "Signed in" with IP and
  "Chrome on Linux" under Recent sign-ins.
- Milestone 2, Linux workspace: backend `ruff check` / `ruff format --check` clean,
  `python -m pytest` **547 passed** (20 new in `tests/test_security_hardening.py`; the
  migration sync and round-trip tests include 0013); frontend lint clean; `npm run e2e`
  **13 passed** (the registration test now also checks that `password1` is refused). In
  headless Chrome, 11 wrong passwords for one email showed "Too many failed sign-in
  attempts for this account. Try again in 7 minutes." with the request ID.

## Phase 8 progress

Plan, screen-to-endpoint map and unsupported features: `docs/PHASE_8_FRONTEND_PLAN.md`.

| Milestone | Scope | Status |
|---|---|---|
| 1 | Repository audit, `docs/PHASE_8_FRONTEND_PLAN.md` | Done |
| 2 | Angular 22 workspace (strict TypeScript and templates, `sf` prefix, OnPush, zoneless), generated API types (`npm run api:types` / `api:check`), typed API services, `ApiError` from the error envelope, dev proxy, design tokens (dark default, light theme), self-hosted Inter and JetBrains Mono, Lucide icons, shell (sidebar, organization switcher, user menu, session-expiry notice), shared components (badges, metrics, states, pagination, dialogs, drawer, toasts, chart) | Done |
| 3 | Login, register, create organization; bearer token in memory + sessionStorage (trade-off documented in the plan), server-side logout, 401 handling with return URL, guards for authentication, organization membership (API-verified) and permissions | Done |
| 4 | Dashboard from real endpoints only: totals via `limit=1`, 7-day workflow outcomes and retries from audit-log windows, event pipeline, connector health, recent events and audit activity, departments, conflicts by severity; per-figure error display | Done |
| 5 | Workforce: employee directory (search, department, status, location, joining-date range, archived, sort, pagination; filters in the URL), add / edit dialog (changed fields only, `If-Match`, `Idempotency-Key`, 412 recovery, manager search), employee page (reporting line, direct reports, sync events, conflicts, change history), terminate (typed confirmation) and archive, departments (add, rename, delete when empty), reporting lines tree, top-bar employee search | Done |
| 5a | Owner-requested changes: password minimum 8 (backend, CLI, docs, tests), show / hide password toggle, Caps Lock notice, strength hint, clear message when the API is not running | Done |
| 6 | Integrations and events: connector catalog and list; create / edit settings / replace credentials from each type's JSON schema (no per-connector UI code); connection test with the normalized error; manual operation for one employee; reconcile summary; disconnect with typed confirmation; linked accounts, dead letters, conflicts and history per connector; event monitor (status, type, employee filters, optional 5 s refresh) and event page (timeline, workflow executions with per-step results, every attempt with HTTP status, error, duration and retry time; refreshes itself until the event settles) | Done |
| 7 | Workflows and reliability: workflow list (trigger / state filters), step builder (trigger, ordered connector + operation steps, reorder, suggested operation per trigger, duplicate and disconnected-connector warnings, 20-step limit), workflow page (step chain, activate / deactivate, execution history with per-step results); reliability overview (retrying events, open dead letters, circuits not closed, audit-log counts for retries / dead letters / circuit openings / replays, connector protection table, recent retries); dead-letter queue (status and connector filters) and entry page (reason, failed step, error, event, other entries for the event, replay with confirmation) | Done |
| 7a | Owner request: collapsible sidebar (icons-only rail on screens wider than 900 px, state kept in the browser; drawer on small screens unchanged) | Done |
| 8 | Data integrity and governance: conflicts list (status, severity, field, application filters) and conflict page (side-by-side values with the authoritative side marked, decide: keep SyncForge's value / use the application's / dismiss, override and note enforced as the API requires, employees:write hint, stale-conflict link to reconcile, history); source-of-truth policies (per field: authoritative system, severity, manual / automatic); audit log (action group, resource, actor, outcome, time range, expandable details, links to the resource); team and roles (add registered users, change roles, remove, own-role and last-admin handling); settings (rename organization, account, memberships, session end, theme, sign out) | Done |
| 9 | Quality: Playwright browser suite against the real stack (13 tests: auth, isolation, workforce, integrations, workflow provisioning, dead-letter replay, conflict resolution, viewer RBAC), axe WCAG 2 A/AA checks on 14 pages in both themes, 390 px phone layout check; fixed colour contrast (tokens), phone overflow (tables in scroll containers, chart table), navigation landmark label. Report: `docs/PHASE_8_FRONTEND_TESTING.md` | Done |
| 10 | `docs/PHASE_8_FRONTEND_ARCHITECTURE.md`, `_COMPONENTS.md`, `_API_INTEGRATION.md`, `_REPORT.md`, ADR-0020, README (screenshots, running the web application), readable conflict-resolution labels in the history | Done |

### Phase 8 verification (actual results)
- Windows, project owner (commit `60d96af`): `npm run e2e` **13 passed** (4.1 min);
  `npm run test:ci` **57 passed**; lint and format clean; build identical to Linux
  (351.66 kB / 96.10 kB).
- Milestone 10, Linux workspace: `npm run test:ci` **57 passed**, lint clean; backend
  `python -m pytest` **527 passed**; screenshots in `docs/screenshots/` taken from the
  running stack.
- Milestone 9, Linux workspace (2026-11-12): `npm run e2e` **13 passed** on two consecutive
  runs (2.5 min each) after fixes; first run had been 4 passed / 9 failed (contrast,
  phone overflow, landmark label, plus test selector and timing mistakes - see
  `docs/PHASE_8_FRONTEND_TESTING.md`). `npm run test:ci` **57 passed** (16 files); lint and
  format (`src` and `e2e`) clean; build success, initial 351.66 kB raw / 96.10 kB transfer;
  `npm audit --omit=dev` 0 vulnerabilities.

- Windows (milestones 1-4, commit `a7e06a7`): `npm ci`, `npx ng build` (initial 340.70 kB),
  `npm run test:ci` **33 passed**, `npx ng lint` clean, `npm run format:check` clean,
  `npm run api:check` types match; the project owner signed up, created an organization
  and used the dashboard against the local stack.
- Milestone 5, Linux workspace (Node 22.23.4): build success (initial 346.1 kB raw /
  94.7 kB transferred); `npm run test:ci` **40 passed** (11 files); lint and format clean.
  Headless Chrome against the running stack: search and status filter reflected in the
  URL; a new employee created with department and manager, and onboarding events completed
  by the worker; while the edit dialog was open the same employee was changed through the
  API, the dialog's save got `412` and showed the concurrent-change message, "Load latest
  version" brought in the other change, and the second save succeeded (version 3); change
  history and sync events listed; terminate with typed confirmation, then archive;
  department added, renamed and deleted; reporting lines drawn three levels deep.

- Milestone 5a, Linux workspace: backend `ruff check` / `ruff format --check` clean,
  `python -m pytest` **527 passed** (new test: an 8-character password is accepted; the
  7-character case is refused); frontend `npm run test:ci` **44 passed**, lint and format
  clean, `npm run api:check` after regenerating the OpenAPI snapshot. Browser: with the
  API stopped, sign-in showed "The SyncForge API is not responding..."; with it running, a
  new account registered with `abcd1234`, the toggle switched the field to plain text.

- Windows, milestone 5 + 5a (commit `42fe0cc`): backend ruff clean, **527 passed**;
  frontend build, **44 passed**, lint and format clean; pushed and checked file by file
  against GitHub (321 tracked files).
- Milestone 6, Linux workspace: build success; `npm run test:ci` **51 passed** (14 files);
  lint and format clean. Headless Chrome against the running stack and mock services: a
  Slack connector created with the mock's test token, connection test passed; settings
  saved (`rate_limit_per_minute: 30`); credentials replaced with a wrong token, the next
  test failed with `authentication` / HTTP 401, credentials replaced again; manual
  `create_user` created the account (shown under linked accounts); a repeat run for the
  same person got the mock's `user_already_exists`, shown as an error; reconcile summary;
  disconnect deleted the credentials; event filters in the URL; an event page showed one
  execution with three steps and their account IDs.

- Windows, milestone 6 (commit `88a1234`): build, **51 passed**, lint, format and API
  check clean; GitHub compared file by file (338 tracked files, all identical).
- Milestone 7, Linux workspace: build success; `npm run test:ci` **53 passed** (15 files);
  lint and format clean. Headless Chrome against the running stack: a termination workflow
  built in the UI (suggested `deactivate_user`, a duplicate step refused before sending,
  created inactive), activated, steps reordered (version 2), deactivated again; with the
  payroll mock answering 503 to every create, a new hire's event reached `dead_letter`
  after 34 s (5 attempts); the fault was cleared, the entry replayed from its page, the
  event then completed; the reliability overview showed the counts from the audit log.

- Windows, milestones 7 and 7a (commits `cd54e12`, `95a96a8`): build, **53 passed**, lint and
  format clean; the owner ran the failure demo (payroll 503 -> dead letter after 5 attempts
  -> replay -> completed) and checked the collapsible sidebar.
- Milestone 8, Linux workspace: build success; `npm run test:ci` **57 passed** (16 files);
  lint and format clean. Headless Chrome against the running stack: a department changed in
  the payroll mock was found by Reconcile (1 conflict); choosing payroll's value against
  the policy kept Resolve disabled until override and a note were given; keeping
  SyncForge's value resolved it and the payroll mock showed Engineering again; a policy
  changed to payroll / automatic and back; the audit log filtered to conflict entries with
  details; an unregistered email was refused with the explanation; a registered user added
  as viewer, then signed in as that viewer: no Audit log in the navigation, `/audit`
  redirected to the forbidden page, no Add employee button, no decision panel on conflicts;
  role changed to integration manager and the member removed; organization renamed and
  renamed back, the sidebar updated.

#### Milestones 1-4, Linux workspace (Node 22.23.4)

- `npx ng build`: success, initial bundle 340.7 kB raw / 93.4 kB transferred; ECharts is a
  lazy chunk (561 kB raw) loaded with the first chart.
- `npm run test:ci`: **33 passed** (9 files). `npx ng lint`: clean. `npm run format:check`:
  clean. `npm run api:check`: types match the snapshot.
- Live: dev server against the running API, worker, relay and mocks, driven in headless
  Chrome: wrong password shows the API's 401 as a sign-in error; a deep link to an
  organization ID that is not valid ends on "Organization not available" after sign-in;
  `/` lands on the user's organization; the dashboard showed the demo organization's real
  figures (12 active employees, 1 of 3 connectors connected, 12 of 13 workflow executions
  succeeded, 16 retries) in dark, light and 390 px mobile layouts.
- `npm audit --omit=dev`: 0 vulnerabilities. `npm audit` (all): 15 moderate, all in the
  ESLint toolchain (`minimatch` ReDoS), development only.

## Phase 7 progress

| Part | Scope | Status | Verified on |
|---|---|---|---|
| 1 | Append-only audit log (`audit_logs`, migration `0010`): written in the same transaction as each change, user or system actor, request ID, no secrets or personal values, trigger refusing UPDATE/DELETE; `GET .../audit-logs`; `audit:read` | Done | Windows 11, Python 3.13.17, Docker PostgreSQL 16, Redis 7 |
| 2 | Optimistic concurrency on employees: `version` (migration `0011`), `ETag`, `If-Match` on PATCH / terminate / archive, `412 version_conflict` | Done | same |
| 3 | Field-level source-of-truth policies, reconciliation (conflict detection), resolution with override / staleness / permission checks, history (`data_source_policies`, `data_conflicts`, `conflict_resolutions`, migration `0012`); connectors read back department, designation, location; `conflicts:read`, `conflicts:resolve`, `policies:manage` | Done | same |
| 4 | docs/14, ADR-0017 to ADR-0019, updates to docs 05, 07, 08, 10, 12, 15, 21, README; demo scenarios 6 (data conflict) and 7 (concurrent edits, audit trail) | Done | Linux workspace; Windows checks reported successful by the project owner (output not recorded here) |

### Phase 7 verification (actual results)

- Windows, after each part: `ruff check .` clean, `alembic check` no drift after migrations
  `0010`, `0011`, `0012`; `python -m pytest`: **484, 496, 526 passed**.
- Live runs in the Linux workspace with the API, worker, relay, Redis and the mocks as
  separate processes:
  - audit: user actions with their request IDs; the worker's `workflow.executed` entry
    carried the hire's request ID (`p7-audit-hire`) and the system as actor;
  - data conflict: a department changed through the payroll mock's own API was detected
    by reconciliation (SyncForge unchanged), adopting payroll's value without override was
    refused (`422 resolution_against_policy`), HR's value was pushed back to payroll, the
    next reconciliation found no conflict; all of it in the audit log;
  - the full demo (seven scenarios, 2.7 minutes): concurrent edits from the same version -
    first save `200`, second `412 version_conflict`, first change kept; 61 audit entries
    for the run (docs/14 section 9).

## Phase 7 acceptance criteria

| Criterion | Evidence |
|---|---|
| Field-level source-of-truth policies, configurable (no universal truth) | `data_source_policies`, defaults in `integrity/fields.py`; `test_api_policies`, `test_an_identity_provider_can_be_authoritative_for_account_status` |
| Conflict detection, history, severity | `services/conflicts.py` reconcile; `test_a_difference_is_recorded_not_overwritten`, `test_a_repeated_detection_refreshes_the_same_conflict`, `test_a_terminated_person_still_active_in_slack_is_critical_and_can_be_deactivated` |
| Configurable resolution policies; manual resolution | manual / auto mode; `test_auto_mode_applies_the_authoritative_value_at_once`, `test_hr_wins_pushes_syncforges_value_to_the_application`, `test_when_the_application_is_authoritative_its_value_is_adopted` |
| Incorrect resolution attempts refused | `test_deciding_against_the_policy_needs_override_and_a_note`, `test_dismissing_needs_a_note_and_a_closed_conflict_stays_closed`, `test_an_unknown_department_is_not_invented` |
| Concurrent update protection; optimistic concurrency | `test_optimistic_concurrency.py`; two-session `test_simultaneous_saves_from_the_same_version_let_exactly_one_win`; `conflict_stale` tests |
| Conflict audit trail | `conflict.detected` / `.resolved` / `.dismissed` entries; `test_personal_values_never_reach_the_audit_log` |
| Audit log of employee, connector, workflow, failure, retry, conflict and permission changes, with organization, actor, action, resource, time, details, outcome | `test_audit.py` |
| No secrets or unnecessary personal data in audit entries | `test_employee_lifecycle_is_audited_without_personal_values`, `test_connector_changes_are_audited_without_secrets` |
| Append-only through the application (and the database) | no update/delete code paths; trigger; `test_entries_cannot_be_updated`, `test_entries_cannot_be_deleted_except_by_an_explicit_retention_transaction` |
| APIs: conflicts list, detail, resolve; audit logs | docs/08 sections 11-12; API tests |
| Authorization | `test_api_requires_audit_read`, `test_adopting_into_the_employee_record_needs_employees_write`, `test_api_reconcile_list_detail_and_resolve`, role matrix |
| Source-of-truth strategy, detection algorithm, policies, concurrency control, audit model, consistency guarantees and limitations documented | docs/14, ADR-0017 to ADR-0019 |
| A complete conflict detection and resolution scenario demonstrated | live runs above |

## Phase 6 progress

| Part | Scope | Status | Verified on |
|---|---|---|---|
| 1 | Retry policy (exponential backoff, proportional jitter, `Retry-After`, bounded attempts); `retrying` statuses and `next_attempt_at`; `synchronization_attempts` history; relay dispatches due retries; `GET .../events/{id}/attempts` (migration `0006`) | Done | Windows 11, Python 3.13.17, Docker PostgreSQL 16, Redis 7 |
| 2 | Dead-letter queue (`dead_letter` status, `dead_letter_events` with the copied error), authorized replay of only the failed steps with a fresh retry budget, `events:replay` permission (migration `0007`) | Done | same |
| 3 | Idempotency keys: `Idempotency-Key: syncforge-job-<id>` on external creates, honoured by the mocks (`in_progress` retryable); `Idempotency-Key` on `POST /employees` stored atomically in `idempotency_records` (migration `0008`) | Done | same |
| 4 | Circuit breaker per connector (closed / open / half-open, shared in PostgreSQL), `rate_limit_per_minute` per connector (deferral without using an attempt), operation deadline across requests (migration `0009`) | Done | same |
| 5 | `python -m app.cli purge-expired` (expired revoked tokens and idempotency records); docs/12, docs/13, ADR-0013 to ADR-0016, updates to docs 05, 07-11, 15, 21, README; `infrastructure/scripts/demo_reliability.py` | Done | Windows 11 (467 passed, `purge-expired` run) and the Linux workspace |

### Phase 6 verification (actual results)

- Windows, after each part: `ruff check .` clean (backend and mock-services),
  `alembic check` no drift after migrations `0006`, `0007`, `0008`, `0009`;
  `python -m pytest`: **414, 430, 449, 466 passed**.
- Part 5: **467 passed on Windows** (one new test for `purge-expired`);
  `python -m app.cli purge-expired` deleted 1 expired revoked token.
- Live runs in the Linux workspace with the API, worker, relay, Redis and the mocks as
  separate processes (docs/12 section 10 has the full output of the final run):
  - transient 503 x2 on payroll: attempts #1, #2 failed, #3 succeeded after ~2 s and ~4 s;
  - retries exhausted: event `dead_letter`, entry `retries_exhausted` with 5 attempts;
    replay `202`, second replay `409 already_replayed`; attempt #6 succeeded; Slack and
    Google not called again;
  - `POST /employees` repeated with one key: same employee, `Idempotent-Replayed: true`,
    one event; a different body with the same key `422 idempotency_key_reused`;
  - payroll answering after the read timeout: attempts timeout, `in_progress` (409), then
    succeeded - one payroll record;
  - Google down during three hires: breaker opened after 5 requests, no requests while
    open, one trial call after 60 s closed it, three accounts in total;
  - Slack limited to 2 calls per minute: the third hire waited for the next minute and then
    made a single attempt.
- Bug found by the first live retry run and fixed before commit: a worker could skip a due
  retry while the relay still held the row (READ COMMITTED); due `retrying` events are now
  claimable; `test_a_worker_claims_a_due_retry_even_while_the_relay_holds_the_row` fails
  without the fix.

## Phase 6 acceptance criteria

| Criterion | Evidence |
|---|---|
| Retry engine: exponential backoff, jitter, configurable maximum, scheduling, history | `reliability/retry.py`, engine, relay; `test_retries.py`; docs/12 sections 3-4 |
| Idempotency: event-ID deduplication, operation IDs, idempotency keys, duplicate prevention | atomic claim and one execution per (event, workflow) (Phase 5); `syncforge-job-<id>` keys; `idempotency_records`; `test_idempotency.py`, `test_workflow_engine.py`; docs/13 |
| Dead-letter queue: storage, error preservation, inspection, manual replay, replay authorization | `dead_letter_events`, `services/dead_letters.py`, `api/v1/dead_letters.py`; `test_dead_letters.py`, concurrency test |
| Rate limiting: HTTP 429, `Retry-After`, configurable connector limits | retry policy; `rate_limit_per_minute`; `test_rate_limit_waits_at_least_retry_after`, `test_jobs_over_the_limit_wait_without_using_an_attempt` |
| Timeouts: connection, read, operation | `connectors/http.py`; `test_timeouts_are_retried`, `test_one_operation_cannot_exceed_its_deadline_across_requests` |
| Circuit breaker: closed, open, half-open, recovery | `reliability/circuit_breaker.py`; `test_circuit_breaker.py` |
| Failure classification; permanent failures not retried | `connectors/errors.py`; `test_permanent_failures_are_not_retried`, `test_permanent_failures_are_dead_lettered_at_once` |
| Tables `synchronization_attempts`, `idempotency_records`, `dead_letter_events` | migrations `0006`-`0009`; docs/07 |
| APIs: dead-letter list, detail, replay; event attempts | docs/08 sections 9-10; API tests |
| Simulations: unavailable service, 429, timeout, duplicate event, worker crash, retry exhaustion, dead-letter replay, circuit breaker | `test_retries.py`, `test_idempotency.py`, `test_workflow_engine.py`, `test_dead_letters.py`, `test_circuit_breaker.py`; demo script |
| Retry, backoff, jitter, idempotency, dead-letter lifecycle, breaker transitions, classification, recovery documented | docs/12, docs/13, ADR-0013 to ADR-0016 |
| Failure, retry, dead-letter transition and successful replay demonstrated | live runs above |

## Phase 5 progress

| Part | Scope | Status | Verified on |
|---|---|---|---|
| 1 | Tables `workflows`, `workflow_steps`, `integration_events`, `outbox_events`, `workflow_executions`, `synchronization_jobs` (migration `0005`); employee changes write events and outbox rows in the same transaction; correlation IDs | Done | Windows 11, Python 3.13.17, Docker PostgreSQL 16 |
| 2 | Workflow configuration API (CRUD, versioning, activate/deactivate, execution history) and events API (list, filters, detail); `workflows:*`, `events:read` permissions | Done | same |
| 3 | Engine (claim with lease, one execution per event and workflow, ordered steps, resume), outbox relay (publish, broker-outage tolerance, lease recovery), Celery worker, Redis in Docker Compose | Done | same, plus Redis 7 in Docker |
| 4 | Documentation (docs/09, docs/11, ADR-0010 to ADR-0012, updates), live verification | Done | same |

### Final Phase 5 verification (actual results)

- `ruff check .` - All checks passed (backend and mock-services)
- `ruff format --check .` - 109 files already formatted (backend), 7 (mock-services)
- `alembic check` - no drift after migration `0005` (upgrade 0004 -> 0005 applied to the
  Windows development database)
- `python -m pytest` - **396 passed on Windows** (57.41 s); checkpoints on Windows after
  each part: 351, 378, 396
- Live run on Windows - API, worker (`--pool=solo`), outbox relay, the three mocks and
  Redis as separate processes:
  - three events recorded while no worker or relay was running waited in the outbox; when
    the relay started it published them (`"count": 3`) and the worker processed them in order
  - hire #2: Slack, Google Workspace and payroll accounts created automatically, each with
    an external ID; task runtime 0.69 s
  - hire #3 with the payroll mock returning 503: Slack and Google `succeeded`, payroll
    `failed` (category `server`), event `failed`
  - hire #1 had been terminated before the worker ran: its three `create_user` steps were
    `skipped` and the termination's `deactivate_user` steps `skipped` - no access created
    for a terminated employee (workers act on current state, docs/09 section 8)
  - every worker log line carried the originating request ID (`demo-hire-N`); logs
    contained IDs only
- Live run in the Linux development workspace, additionally: worker killed (`kill -9`)
  while a slow Google call was in progress; the relay re-dispatched the event after the
  lease expired and the restarted worker completed it on attempt 2 with no duplicate
  account. This run found a bug - recovery renewed the lease, so the next worker skipped
  the event - fixed before commit and covered by
  `test_relay_recovery_hands_a_crashed_workers_event_to_the_next_worker`.
- The Windows crash-recovery demonstration was optional and not run; crash recovery on
  Windows is covered by the automated tests above.

## Phase 5 acceptance criteria

| Criterion | Evidence |
|---|---|
| Create, update, activate, deactivate workflows; configure triggers and steps | `api/v1/workflows.py`, `services/workflows.py`; `test_workflows_api.py` |
| Steps executed sequentially; workflow and per-step status tracked | `workflows/engine.py`; `test_onboarding_creates_accounts_in_every_application`, `test_a_failed_step_fails_the_execution_and_skips_the_rest` |
| Execution history | `GET .../workflows/{id}/executions`, `GET .../events/{id}`; `test_execution_history_shows_per_step_status`, `test_event_detail_includes_executions_and_steps` |
| Example onboarding and termination workflows | `test_onboarding_...`, `test_offboarding_deactivates_the_accounts`; Windows live run |
| Persistent events with IDs, payload validation, history, status updates | `integration_events`; `test_event_outbox.py`, `test_events_api.py` |
| Redis broker and background workers, asynchronous processing | `docker-compose.yml`, `workers/`; `test_celery_worker.py`; Windows live run |
| Transactional outbox | `events/outbox.py`, `events/relay.py`; `test_employee_change_and_its_events_share_one_transaction`, `test_outbox_relay.py` |
| At-least-once delivery with idempotent processing (no exactly-once claim) | `test_duplicate_delivery_is_skipped_and_creates_nothing_twice`, `test_an_event_owned_by_a_live_worker_is_not_claimed_twice`; docs/09 section 7 |
| Correlation IDs | `correlation_id` on events, worker log context; `test_create_records_one_pending_event_...`, `test_the_correlation_id_travels_with_the_message` |
| Worker restart behaviour | `test_a_crashed_worker_is_resumed_without_repeating_finished_work`, `test_relay_recovery_hands_...`; Linux live crash run |
| Event-driven architecture, event lifecycle, outbox, broker, worker architecture, workflow state machine, execution sequence, failure boundaries documented with Mermaid diagrams | `docs/09`, `docs/11`, `docs/05`, `docs/07`, ADR-0010 to ADR-0012 |
| Complete onboarding demonstrated with the mock integrations | Windows live run (hire #2) |

## Phase 4 progress

| Part | Scope | Status | Verified on |
|---|---|---|---|
| 1 | Connector core: interface, registry, versioning, hardened HTTP client, error normalization; Fernet credential encryption; tables `connectors`, `connector_credentials`, `external_accounts` (migration `0004`) | Done | Windows 11, Python 3.13.17, Docker PostgreSQL 16 |
| 2 | Mock Slack / Google Workspace / payroll services with failure injection; Slack, Google (OAuth token lifecycle) and payroll adapters; adapter tests over real HTTP | Done | same |
| 3 | Connector service and API: catalog, CRUD, encrypted credentials, connection tests, rotation, disconnect, operations, linked accounts; `connectors:*` permissions | Done | same |
| 4 | Documentation, live demonstration | Done | same |

### Final Phase 4 verification (actual results)

- `ruff check .` - All checks passed (backend and mock-services)
- `ruff format --check .` - 86 files already formatted (backend), 6 (mock-services)
- `alembic check` - no drift after migration `0004`
- `python -m pytest` - **332 passed** (includes 25 adapter tests and 28 API tests against
  the mock services running as real HTTP servers), on Windows (47.36 s) and in the Linux
  development workspace.
- Live demonstration on Windows (API and Slack mock as separate processes): connector
  created (`pending`, fingerprint only); the first connection test consumed a fault left
  queued in the mock and correctly reported `ok: false`, `category: server`; `create_user`
  created the Slack account in 32.61 ms; an injected 503 returned `502 connector_error`
  (`category: server, retryable: true`) with the same `request_id` in the response and the
  API log; the log contained no credentials.
- Live demonstration in the Linux workspace with all three mocks: all three connectors
  tested `ok`; `create_user` succeeded in Slack, Google Workspace and payroll; after a Slack
  503 the retry succeeded; after the Google mock expired every token the next operation
  refreshed the token and succeeded.
- Two Windows-only issues found and fixed during verification: the refused-connection test
  (Windows retries refused loopback connections ~2 s) and `localhost` default URLs (IPv6
  first, ~2 s per call); see docs/10 section 13 and docs/21.

## Phase 4 acceptance criteria

| Criterion | Evidence |
|---|---|
| Common connector interface, registration, configuration, versioning | `connectors/base.py`, `registry.py`; `test_connector_core.py` (registry, major-version refusal) |
| Slack, Google Workspace and mock payroll connectors | `connectors/slack.py`, `google_workspace.py`, `payroll.py`; `test_connector_adapters.py` (each runs the same lifecycle) |
| Real vs simulated clearly distinguished | `simulated: true` in the catalog; docs/10 section 1; mock-services/README.md |
| OAuth configuration and lifecycle | Google adapter token exchange, caching and refresh; `test_google_token_is_cached_between_calls`, `test_google_gets_a_new_token_when_the_old_one_expires` |
| Secure credential handling | Fernet encryption, never returned/logged/echoed; `test_encryption.py`, `test_create_connector_encrypts_credentials_and_never_returns_them`, `test_logs_never_contain_credentials` |
| Connection testing and health status | `POST .../test`; status `pending`/`connected`/`error`/`disconnected` with last error; API tests |
| Error normalization, timeouts, rate-limit responses | `connectors/errors.py`, `http.py`; adapter tests for 401, 404, 409, 503, 429 + `Retry-After`, read timeout, refused connection |
| Mock services with success and failure simulation | `mock-services/`; fault queue (status, rate limit, timeout) and Google token expiry |
| APIs: list, create, get, test, disconnect (+ update, operations, accounts) | `api/v1/connectors.py`; `test_connectors_api.py` |
| At least two working integrations demonstrated through actual API calls | Live demonstrations above (Slack on Windows; all three in the workspace) |
| Adapter pattern, interface, auth architecture, OAuth lifecycle, credential security, registration, error normalization, adding a connector documented with class and sequence diagrams | `docs/10`, `docs/07`, `docs/08`, `docs/15`, ADR-0008, ADR-0009 |

## Phase 3 progress

| Part | Scope | Status | Verified on |
|---|---|---|---|
| 1 | Tables `departments`, `employees` (migration `0003`): composite same-organization foreign keys, lifecycle check constraints, indexes; pure lifecycle event detection | Done | Windows 11, Python 3.13.17, Docker PostgreSQL 16 |
| 2 | Departments and employees APIs: CRUD, search, filters, sorting, pagination, terminate, archive; cycle prevention with advisory lock; new permissions | Done | same |
| 3 | `seed-demo` command, documentation, live verification | Done | same |

### Final Phase 3 verification (actual results)

- `ruff check .` - All checks passed
- `ruff format --check .` - 65 files already formatted
- `alembic check` - no drift after migration `0003`
- `python -m pytest` - **208 passed** (includes two two-session concurrency tests)
- `seed-demo` created "Acme Demo": 5 departments, 20 employees; running it again is refused
- Live API run against the demo data: list total 20; search "shah" -> Vikram Shah;
  department counts Engineering 8, Finance 2, People Operations 2, Product 3, Sales 5;
  `on_leave` filter -> Ishita Banerjee; `terminated` filter -> Rahul Desai, whose report
  now reports to Vikram Shah; making the CEO report to an engineering manager ->
  `422 manager_cycle`
- Server log: lifecycle events contain IDs and field names only (no names or emails)

## Phase 3 acceptance criteria

| Criterion | Evidence |
|---|---|
| Create, retrieve, update, archive employees | `test_employees_api.py` (create, get, update, archive tests) |
| Search, filter, paginate | `test_search`, `test_filters`, `test_sorting`, `test_pagination_is_stable_and_complete` |
| Employee status management and lifecycle transitions | `test_status_can_move_between_active_and_on_leave`, terminate and archive tests, DB check constraints in `test_employee_models.py` |
| Department management | `test_departments_api.py` |
| Manager relationships | composite FK tests, `test_manager_cycles_are_rejected`, `test_terminate_reassigns_direct_reports`, concurrency test |
| All required employee fields | `employees` table (docs/07); "last updated" is `updated_at` |
| Lifecycle events identified (`created`, `updated`, `department_changed`, `manager_changed`, `terminated`) | `test_lifecycle_events.py`; event assertions in `test_employees_api.py` |
| Invalid data and duplicate identifiers rejected | `test_create_rejects_invalid_input`, `test_create_rejects_duplicates`, uniqueness tests in `test_employee_models.py` |
| Organization isolation | `test_cross_organization_access_is_404_everywhere`, `test_list_never_includes_other_organizations`, composite FK tests |
| Sensitive data not exposed unnecessarily | no PII in logs (`test_create_employee`), `Employee.__repr__`, work fields only |
| Domain model, lifecycle, validation, relationships, API contracts, pagination, event generation documented | `docs/06`, `docs/07`, `docs/08`, `docs/15`, ADR-0006, ADR-0007 |

## Phase 2 progress

| Part | Scope | Status | Verified on |
|---|---|---|---|
| 1 | FastAPI app, settings, JSON logging, request IDs, error envelope, `/health`, `/ready`, PostgreSQL in Docker | Done | Windows 11, Python 3.13.17, Docker PostgreSQL 16 |
| 2 | Tables `organizations`, `users`, `organization_memberships`; Alembic migration `0001` | Done | same |
| 3 | Argon2id hashing, JWT, register / login / me / logout, `revoked_tokens` (migration `0002`) | Done | same |
| 4 | Organizations API, role permissions, organization isolation, member management, last-admin rule, Super Admin CLI | Done | same |
| 5 | Clean-clone verification from GitHub, phase report | Done | same |

### Final Phase 2 verification (actual results)

- `ruff check .` - All checks passed
- `ruff format --check .` - 50 files already formatted
- `python -m pytest` - **111 passed** (includes a two-session row-locking concurrency test)
- Live run: register -> login -> `/me` -> logout -> `/me` returned `401 token_revoked`
- Live run: create org -> add viewer -> viewer rename `403` -> outsider read `404` ->
  last admin self-demotion `409 last_admin`
- Clean clone from GitHub, set up only by following the README: migrations `0001` and
  `0002` applied to an empty database, `alembic check` reports no drift, 111 tests passed,
  no secret files tracked by Git

## Phase 2 acceptance criteria

| Criterion | Evidence |
|---|---|
| FastAPI app with modular layers | `backend/app/{api,core,models,repositories,schemas,security,services}` |
| PostgreSQL, SQLAlchemy, Alembic migrations | Migrations `0001`, `0002`; `test_migrations.py` |
| Environment configuration, logging, error handling | `app/core/`; `test_health.py` |
| `/health` and `/ready` | `test_health.py` (including database-down case) |
| Registration, login, logout, `/me`, password hashing, JWT | `test_auth_api.py`, `test_security.py` |
| Invalid credentials, expired and missing tokens | `test_auth_api.py`, `test_security.py` |
| Organizations, memberships, user management | `test_organizations_api.py` |
| Four roles and permission checks | `test_authorization.py`, `test_organizations_api.py` |
| Cross-organization access prevention | `test_admin_of_one_org_cannot_touch_another` and others |
| Database constraints and connectivity | `test_models.py`, `test_ready_*` |
| Architecture, auth flow, JWT lifecycle, authorization, multi-tenancy, ER diagram, errors documented | `docs/05`, `docs/07`, `docs/08`, `docs/15`, ADR-0001 to ADR-0005 |

## Phase 1 verification (Windows 11 machine)

| Tool | Version |
|---|---|
| Python | 3.13.17 (via py launcher; 3.10.5 also installed, not used) |
| pip | 26.2.2 |
| Node.js / npm | 24.18.0 / 11.16.0 |
| Angular CLI / TypeScript | 22.2.6 / 7.0.2 |
| Git | 2.40.1 |
| Docker / Compose | 29.9.3 / v5.7.0 (WSL 2) |
| GitHub CLI | 2.103.3 |

## Known limitations (current)

- Idempotency keys towards external applications are honoured by the three mock services;
  the real Slack SCIM and Google Directory APIs do not document such a header. Against
  them, a crash between the external create and SyncForge storing the link produces a
  `conflict` and a dead-letter entry (visible, not a duplicate). "Find before create"
  (adopting an existing account by email) is not implemented (docs/13 section 3).
- A long outage dead-letters work after the retry budget (about 30 s of backoff, longer
  with `Retry-After` or an open circuit); it is restarted by replaying the entries, one at
  a time (no bulk replay yet).
- Circuit-breaker and rate-limit state are rows in PostgreSQL, updated on every external
  call to that connector - fine at provisioning volumes; the rate limit is a fixed
  one-minute window (up to twice the limit across a boundary).
- `python -m app.cli purge-expired` must be scheduled by the operator (cron / Task
  Scheduler); SyncForge has no built-in scheduler.
- Several workers do not guarantee per-employee ordering (steps read current state, so this
  is safe today). Worker and relay health is reported by `GET /system/status` (Phase 9).
- Event, outbox, execution, attempt and dead-letter tables are never pruned (retention job:
  future improvement).
- All three connectors are simulated (verified against local mocks only); real Slack and
  Google need real tenants and, for Google, the JWT-bearer grant (docs/10 section 1).
- OAuth tokens are cached per process; the browser authorization-code flow is not implemented.
- The SSRF allowlist matches host names, not resolved IP addresses.
- Optimistic concurrency covers employees; clients that send no `If-Match` still get
  last-write-wins (the Phase 8 UI will always send it).
- Reconciliation runs on demand (or as scheduled by the operator), up to 500 accounts per
  run, seven fields; conflicts are found when it runs, not instantly.
- No retention job for audit, conflict, event or execution history yet.
- Termination is final; rehiring means creating a new employee record.
- Free-text employee search is a substring scan within one organization (no trigram index).
- Members can only be added if they already registered (no email invitations yet).
- Passwords: minimum 8 characters and a common-password check (bundled list of 2,087
  entries, not a full breach corpus); no MFA yet. NIST SP 800-63B-4 recommends 15+
  characters when a password is the only factor.
- No refresh tokens: users log in again after 30 minutes.
- One unidentified intermittent test failure seen once at the end of Phase 5 (Linux
  workspace, 1 of 15 full runs, test name not captured). It has not reappeared since: in
  the Phase 9 quality pass the suite passed 5 times in order and 3 times in random order
  (docs/16 section 5).
- Substring search and the organization summary read the whole organization (38-40 ms at
  10,000 employees on the 2-CPU test machine; options in docs/19 section 5).
- Browser sign-in uses a bearer token in sessionStorage (not an HttpOnly cookie).
