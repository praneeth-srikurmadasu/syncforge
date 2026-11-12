# SyncForge - Project Status

**Current phase:** 4 complete - awaiting approval to start Phase 5 (Workflow engine and event processing)
**Last updated:** 2026-11-11

| Phase | Status |
|---|---|
| 1 - Environment and repository | Complete |
| 2 - Backend foundation, auth, organizations | Complete |
| 3 - Employee management | Complete |
| 4 - Connector framework and mock services | Complete |
| 5 - Workflow engine and event processing | Next (awaiting approval) |
| 6-10 | Not started |

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
  the mock services running as real HTTP servers) in the Linux development workspace;
  the Windows run was reported as all passing (Part 2 checkpoint on Windows: 299 passed).
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

- Connector operations are synchronous, admin-triggered and attempted once; automatic
  execution is Phase 5, retries/idempotency/circuit breaker are Phase 6.
- All three connectors are simulated (verified against local mocks only); real Slack and
  Google need real tenants and, for Google, the JWT-bearer grant (docs/10 section 1).
- OAuth tokens are cached per process; the browser authorization-code flow is not implemented.
- The SSRF allowlist matches host names, not resolved IP addresses.
- Lifecycle events are only logged; durable storage (transactional outbox) and processing
  arrive in Phase 5.
- Two admins changing the same employee field from stale screens: last write wins
  (optimistic concurrency is Phase 7).
- Termination is final; rehiring means creating a new employee record.
- Free-text employee search is a substring scan within one organization (no trigram index).
- Members can only be added if they already registered (no email invitations yet).
- No rate limiting on login/register yet - Phase 9.
- Expired `revoked_tokens` rows are not cleaned up automatically yet - Phase 5.
- No refresh tokens: users log in again after 30 minutes.
