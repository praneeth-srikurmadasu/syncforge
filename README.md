# SyncForge

**Universal Workforce Integration & Synchronization Platform**

SyncForge keeps employee data consistent across HR, Slack, Google Workspace and payroll by
turning workforce changes (hire, transfer, termination) into reliably processed, audited
synchronization events.

> **Status: Phase 2 of 10 in progress — backend foundation and authentication.**
> See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for exactly what works today.

## What works today

- FastAPI backend with structured JSON logs, request IDs and one consistent error format
- `/health` (liveness) and `/ready` (database readiness) probes
- PostgreSQL 16 in Docker Compose, schema managed by Alembic migrations
- Organizations, users and role-based memberships (data model)
- Registration, login with JWT access tokens, `/me`, and logout that truly revokes the token
- 55 automated tests against a real PostgreSQL database

## Tech stack

| Layer | Technology | Status |
|---|---|---|
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | ✅ in use |
| Database | PostgreSQL 16 (Docker) | ✅ in use |
| Auth | Argon2id password hashing, JWT (PyJWT) | ✅ in use |
| Testing | Pytest, Starlette TestClient | ✅ in use |
| Background jobs | Redis 7 + Celery | Phase 5 |
| Frontend | Angular 22, TypeScript | Phase 8 |
| CI | GitHub Actions | Phase 10 |

## Quick start (Windows PowerShell)

Prerequisites: Python 3.13 (`py -3.13`), Docker Desktop, Git.
Full installation guide for each tool: see the Phase 1 notes in [`PROJECT_STATUS.md`](PROJECT_STATUS.md).

```powershell
# 1. Configuration (from the repository root)
Copy-Item .env.example .env
$secret = py -3.13 -c "import secrets; print(secrets.token_urlsafe(64))"
(Get-Content .env) -replace '^JWT_SECRET_KEY=.*', "JWT_SECRET_KEY=$secret" | Set-Content .env -Encoding ascii

# 2. Start PostgreSQL
docker compose up -d postgres

# 3. Backend environment
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# 4. Create the database schema
alembic upgrade head

# 5. Run the API
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/docs** for the interactive API documentation.

On macOS/Linux use `cp .env.example .env`, `python3.13 -m venv .venv` and
`source .venv/bin/activate`.

## Running tests and checks

From `backend/` with the virtual environment active and PostgreSQL running:

```powershell
ruff check .            # lint
ruff format --check .   # formatting
python -m pytest -v     # tests (uses a separate syncforge_test database)
```

## Repository layout

```
backend/
  app/
    api/            HTTP routers (/health, /ready, /api/v1/...)
    core/           settings, logging, middleware, errors, database engine
    models/         SQLAlchemy tables
    repositories/   database queries
    schemas/        request/response contracts
    security/       password hashing, JWT
    services/       business rules and transactions
  migrations/       Alembic migrations (0001, 0002, ...)
  tests/            pytest suite
docs/               architecture, database, API, security, ADRs
frontend/           Angular app (Phase 8)
mock-services/      mock Slack / Google Workspace / payroll APIs (Phase 4)
infrastructure/     Dockerfiles and scripts (later phases)
docker-compose.yml  local PostgreSQL (more services added per phase)
```

## Documentation

| Document | Contents |
|---|---|
| [System architecture](docs/05-system-architecture.md) | Components, layers, request lifecycle, errors, logging |
| [Database design](docs/07-database-design.md) | ER diagram, tables, constraints, migrations, transactions |
| [API design](docs/08-api-design.md) | Conventions, error codes, endpoint reference |
| [Security design](docs/15-security-design.md) | Auth flow, JWT lifecycle, passwords, secrets |
| [Architecture decisions](docs/adr/) | ADR-0001 … ADR-0004 |
| [Project plan](PROJECT_PLAN.md) · [Status](PROJECT_STATUS.md) · [Changelog](CHANGELOG.md) | Progress tracking |
