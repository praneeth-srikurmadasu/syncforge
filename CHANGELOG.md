# Changelog

All notable changes to SyncForge are recorded here.

## [Unreleased]

### Phase 2 - Backend foundation, authentication and organizations (in progress)

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

### Phase 1 - Development environment and repository setup
- Initialized Git repository on `main` with project folder structure.
- Added README, PROJECT_PLAN, PROJECT_STATUS, .gitignore, .gitattributes, .editorconfig, .env.example.
