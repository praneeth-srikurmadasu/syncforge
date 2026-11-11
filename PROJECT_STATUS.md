# SyncForge - Project Status

**Current phase:** 3 complete - awaiting approval to start Phase 4 (Connector framework)
**Last updated:** 2026-11-11

| Phase | Status |
|---|---|
| 1 - Environment and repository | Complete |
| 2 - Backend foundation, auth, organizations | Complete |
| 3 - Employee management | Complete |
| 4 - Connector framework and mock services | Next (awaiting approval) |
| 5-10 | Not started |

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
