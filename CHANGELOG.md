# Changelog

All notable changes to SyncForge are recorded here.

## [Unreleased]

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
