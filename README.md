# SyncForge

**Universal Workforce Integration & Synchronization Platform**

SyncForge keeps employee data consistent across HR, Slack, Google Workspace and payroll by
turning workforce changes (hire, transfer, termination) into reliably processed, audited
synchronization events.

> **Status: Phase 4 of 10 complete - connector framework. Next: Phase 5, workflow engine and event processing.**
> See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for exactly what works today.

## What works today

- FastAPI backend with structured JSON logs, request IDs and one consistent error format
- `/health` (liveness) and `/ready` (database readiness) probes
- PostgreSQL 16 in Docker Compose, schema managed by Alembic migrations
- Registration, login with JWT access tokens, `/me`, and logout that truly revokes the token
- Organizations API with four roles (Super Admin, Organization Admin, Integration Manager,
  Viewer), permission checks, and strict organization isolation (outsiders get 404)
- Member management with a concurrency-safe "at least one admin" rule
- Departments and employees API: create, search, filter, sort, paginate, update, terminate
  (direct reports move up) and archive, with tenant integrity enforced by the database
- Employee lifecycle events (`employee.created`, `.updated`, `.department_changed`,
  `.manager_changed`, `.terminated`) detected on every change and logged without personal data
- Reporting-line cycle prevention that is safe under concurrent requests
- `seed-demo` command that creates a realistic demo organization
- Connector framework: one interface, three adapters (Slack SCIM, Google Workspace
  Directory with OAuth token lifecycle, payroll API key) with credentials encrypted at
  rest, connection tests, normalized and classified errors (429 `Retry-After`, timeouts,
  5xx), SSRF protection, and manual provisioning operations
- Local mock Slack, Google Workspace and payroll services with on-demand failure injection
  (**simulated** - see [mock-services/README.md](mock-services/README.md))
- 332 automated tests against a real PostgreSQL database, including two-session
  concurrency tests and connector tests over real HTTP against the mocks

## Tech stack

| Layer | Technology | Status |
|---|---|---|
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | in use |
| Database | PostgreSQL 16 (Docker) | in use |
| Auth | Argon2id password hashing, JWT (PyJWT) | in use |
| Integrations | httpx2 (HTTP client), cryptography (Fernet credential encryption) | in use |
| Testing | Pytest, Starlette TestClient | in use |
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

Connectors need an encryption key for their credentials. Generate one and put it in `.env`:

```powershell
$key = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
(Get-Content ..\.env) -replace '^CONNECTOR_ENCRYPTION_KEY=.*', "CONNECTOR_ENCRYPTION_KEY=$key" | Set-Content ..\.env -Encoding ascii
```

To use connectors locally, start the mock services (one terminal each, from the repository
root) - see [mock-services/README.md](mock-services/README.md):

```powershell
uvicorn mockservices.slack:app --port 9101 --app-dir mock-services
uvicorn mockservices.google_workspace:app --port 9102 --app-dir mock-services
uvicorn mockservices.payroll:app --port 9103 --app-dir mock-services
```

Optional - load demo data. Register a user first (for example through `/docs`), then:

```powershell
python -m app.cli seed-demo --admin-email you@example.com
```

This creates the "Acme Demo" organization with 5 departments and 20 fictional employees, and
makes you its Organization Admin.

Optional - create a platform Super Admin (prompts for a password):

```powershell
python -m app.cli create-superadmin --email admin@example.com --name "Platform Admin"
```

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
    security/       password hashing, JWT, roles and permissions
    services/       business rules and transactions
    events/         lifecycle event detection (pure functions)
    connectors/     connector interface, registry, HTTP client, Slack/Google/payroll adapters
    cli.py          operator commands (create-superadmin, seed-demo)
    seed.py         demo data
  migrations/       Alembic migrations (0001-0004)
  tests/            pytest suite
docs/               architecture, database, API, security, ADRs
frontend/           Angular app (Phase 8)
mock-services/      mock Slack / Google Workspace / payroll APIs (simulated, failure injection)
infrastructure/     Dockerfiles and scripts (later phases)
docker-compose.yml  local PostgreSQL (more services added per phase)
```

## Documentation

| Document | Contents |
|---|---|
| [System architecture](docs/05-system-architecture.md) | Components, layers, request lifecycle, errors, logging |
| [Component design](docs/06-component-design.md) | Employee domain model, lifecycle, validation layers, events, concurrency |
| [Database design](docs/07-database-design.md) | ER diagram, tables, constraints, migrations, transactions |
| [API design](docs/08-api-design.md) | Conventions, error codes, endpoint reference |
| [Connector framework](docs/10-connector-framework.md) | Interface, adapters, real vs simulated, error normalization, OAuth lifecycle, credential security, adding a connector |
| [Security design](docs/15-security-design.md) | Auth flow, JWT lifecycle, passwords, secrets, roles, tenant isolation, connector credentials, SSRF |
| [Troubleshooting](docs/21-troubleshooting.md) | Investigating failed requests, connector errors, test and Windows issues |
| [Architecture decisions](docs/adr/) | ADR-0001 to ADR-0009 |
| [Project plan](PROJECT_PLAN.md), [Status](PROJECT_STATUS.md), [Changelog](CHANGELOG.md) | Progress tracking |
