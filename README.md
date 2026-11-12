# SyncForge

**Universal Workforce Integration & Synchronization Platform**

SyncForge keeps employee data consistent across HR, Slack, Google Workspace and payroll by
turning workforce changes (hire, transfer, termination) into reliably processed, audited
synchronization events.

> **Status: Phase 5 of 10 complete - workflow engine and event processing. Next: Phase 6, reliability engine (retries, idempotency keys, dead-letter queue, circuit breaker).**
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
- **Automatic provisioning**: configurable workflows (trigger + ordered connector steps)
  run by Celery workers when employees are hired, changed or terminated - e.g. hire someone
  and their Slack, Google and payroll accounts are created about a second later
- **Transactional outbox**: an employee change and its events commit together; an outbox
  relay publishes them to Redis and re-sends events whose worker crashed
- At-least-once delivery with idempotent processing: duplicate deliveries are skipped, a
  crashed worker's event is resumed without repeating finished steps, and a late event
  never creates accounts for someone already terminated
- Events and workflow execution history with per-step status through the API, traceable in
  the logs by the originating request ID
- 396 automated tests against a real PostgreSQL database, including two-session
  concurrency tests, connector tests over real HTTP against the mocks, and a real Celery
  worker

## Tech stack

| Layer | Technology | Status |
|---|---|---|
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | in use |
| Database | PostgreSQL 16 (Docker) | in use |
| Auth | Argon2id password hashing, JWT (PyJWT) | in use |
| Integrations | httpx2 (HTTP client), cryptography (Fernet credential encryption) | in use |
| Testing | Pytest, Starlette TestClient | in use |
| Background jobs | Redis 7 (broker), Celery 5.7 (workers) | in use |
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

# 2. Start PostgreSQL and Redis
docker compose up -d postgres redis

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

### Run the whole system (automatic provisioning)

Besides the API, run the mock services, a worker and the outbox relay, each in its own
terminal. The commands use absolute folders and the project's own `python.exe`, so they work
from any terminal and never pick up another project's tools from `PATH`:

```powershell
# mock Slack / Google Workspace / payroll (simulated)
Set-Location "$HOME\Projects\syncforge\mock-services"
& "$HOME\Projects\syncforge\backend\.venv\Scripts\python.exe" -m mockservices.run_all

# worker (Windows needs --pool=solo)
Set-Location "$HOME\Projects\syncforge\backend"
& "$HOME\Projects\syncforge\backend\.venv\Scripts\python.exe" -m celery -A app.workers.celery_app worker --loglevel=INFO --pool=solo

# outbox relay
Set-Location "$HOME\Projects\syncforge\backend"
& "$HOME\Projects\syncforge\backend\.venv\Scripts\python.exe" -m app.cli outbox-relay
```

(Adjust `$HOME\Projects\syncforge` if you cloned elsewhere.) Then create connectors and an
active workflow through the API ([docs/08](docs/08-api-design.md), sections 7-8) and add an
employee: the event appears under `GET .../events` and is processed within about a second.
How it works: [docs/09](docs/09-event-driven-architecture.md),
[docs/11](docs/11-workflow-engine.md).

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
    connectors/     connector interface, registry, HTTP client, Slack/Google/payroll adapters
    events/         lifecycle detection, transactional outbox, outbox relay
    workflows/      workflow engine (claim, plan, run steps, record outcomes)
    workers/        Celery app and tasks
    cli.py          operator commands (create-superadmin, seed-demo, outbox-relay)
    seed.py         demo data
  migrations/       Alembic migrations (0001-0005)
  tests/            pytest suite
docs/               architecture, database, API, security, ADRs
frontend/           Angular app (Phase 8)
mock-services/      mock Slack / Google Workspace / payroll APIs (simulated, failure injection)
infrastructure/     Dockerfiles and scripts (later phases)
docker-compose.yml  local PostgreSQL and Redis (more services added per phase)
```

## Documentation

| Document | Contents |
|---|---|
| [System architecture](docs/05-system-architecture.md) | Components, layers, request lifecycle, errors, logging |
| [Component design](docs/06-component-design.md) | Employee domain model, lifecycle, validation layers, events, concurrency |
| [Database design](docs/07-database-design.md) | ER diagram, tables, constraints, migrations, transactions |
| [API design](docs/08-api-design.md) | Conventions, error codes, endpoint reference |
| [Event-driven architecture](docs/09-event-driven-architecture.md) | Transactional outbox, relay, Redis, Celery workers, leases, delivery guarantees |
| [Connector framework](docs/10-connector-framework.md) | Interface, adapters, real vs simulated, error normalization, OAuth lifecycle, credential security, adding a connector |
| [Workflow engine](docs/11-workflow-engine.md) | Workflows, executions, job states, processing sequence, failure boundaries |
| [Security design](docs/15-security-design.md) | Auth flow, JWT lifecycle, passwords, secrets, roles, tenant isolation, connector credentials, SSRF |
| [Troubleshooting](docs/21-troubleshooting.md) | Investigating failed requests and synchronizations, connector, worker, test and Windows issues |
| [Architecture decisions](docs/adr/) | ADR-0001 to ADR-0012 |
| [Project plan](PROJECT_PLAN.md), [Status](PROJECT_STATUS.md), [Changelog](CHANGELOG.md) | Progress tracking |
