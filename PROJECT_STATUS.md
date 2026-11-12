# SyncForge - Project Status

**Current phase:** 5 complete - awaiting approval to start Phase 6 (Reliability engine and failure recovery)
**Last updated:** 2026-11-12

| Phase | Status |
|---|---|
| 1 - Environment and repository | Complete |
| 2 - Backend foundation, auth, organizations | Complete |
| 3 - Employee management | Complete |
| 4 - Connector framework and mock services | Complete |
| 5 - Workflow engine and event processing | Complete |
| 6 - Reliability engine and failure recovery | Next (awaiting approval) |
| 7-10 | Not started |

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

- Workflow steps are attempted once per execution: a failed step fails the event; retries
  with backoff, dead-lettering, replay, idempotency keys towards external APIs and the
  circuit breaker are Phase 6.
- A worker crash in the one-commit window after an external application created an account
  but before SyncForge stored the link makes the resumed `create_user` fail with "already
  exists" (Phase 6, idempotency keys).
- Several workers do not guarantee per-employee ordering (steps read current state, so this
  is safe today); worker and relay health endpoints are Phase 9.
- Event, outbox and execution tables are never pruned (retention job: future improvement).
- All three connectors are simulated (verified against local mocks only); real Slack and
  Google need real tenants and, for Google, the JWT-bearer grant (docs/10 section 1).
- OAuth tokens are cached per process; the browser authorization-code flow is not implemented.
- The SSRF allowlist matches host names, not resolved IP addresses.
- Two admins changing the same employee field from stale screens: last write wins
  (optimistic concurrency is Phase 7).
- Termination is final; rehiring means creating a new employee record.
- Free-text employee search is a substring scan within one organization (no trigram index).
- Members can only be added if they already registered (no email invitations yet).
- No rate limiting on login/register yet - Phase 9.
- Expired `revoked_tokens` rows are not cleaned up automatically yet - planned as a periodic
  maintenance task in Phase 6.
- No refresh tokens: users log in again after 30 minutes.
- One unidentified intermittent test failure: in the Linux workspace, 1 of 15 full
  runs of the suite reported `1 failed, 395 passed`, without the test name being captured.
  It did not reappear in the following 14 full runs or in 15 runs of the connector, engine,
  relay, worker and events test files; all Windows runs passed. To be pinned down in the
  Phase 9 quality pass (or earlier if it reappears).
