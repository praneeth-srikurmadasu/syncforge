# SyncForge

[![CI](https://github.com/praneeth-srikurmadasu/syncforge/actions/workflows/ci.yml/badge.svg)](https://github.com/praneeth-srikurmadasu/syncforge/actions/workflows/ci.yml)

**Universal Workforce Integration & Synchronization Platform**

SyncForge keeps employee data consistent across HR, Slack, Google Workspace and payroll by
turning workforce changes (hire, transfer, termination) into reliably processed, audited
synchronization events.

> **Status: Phase 9 of 10 complete - security hardening, API versioning, observability and performance measurements on top of the backend (Phases 2-7) and the Angular application (Phase 8). Next: Phase 10, Docker, CI and final delivery.**
> See [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for exactly what works today.

## Screenshots

Real screens of the running application against the local stack (the connectors are the
**simulated** local services).

| | |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Event detail](docs/screenshots/event-detail.png) |
| Dashboard: every figure and chart read from the API | An onboarding event: three connector steps and every attempt |
| ![Dead-letter entry](docs/screenshots/dead-letter.png) | ![Conflict, light theme](docs/screenshots/conflict.png) |
| A dead-lettered step after five failed attempts, then replayed | A department conflict between SyncForge and payroll, light theme |

## What works today

### Web application (Angular)

- Sign-up, sign-in and sign-out with server-side revocation, session-expiry warning, and
  return to the requested page after signing in again
- Every screen scoped to an organization in the URL; membership checked by the API;
  navigation and actions shown according to the user's role
- Dashboard built only from real API data, including 7-day workflow and retry history
  read from the audit log
- Employees (search, filters in the URL, add / edit with concurrent-edit protection,
  terminate, archive), departments, reporting lines
- Connectors (forms generated from each connector type's schema, connection test,
  manual operations, reconcile, disconnect), workflows (step builder, activate /
  deactivate, execution history), event monitor with per-attempt detail
- Reliability overview, dead-letter queue with replay, data conflicts with
  policy-aware resolution, source-of-truth policies, audit log, team and roles, settings
- Dark and light themes, collapsible sidebar, phone layouts, WCAG AA colour contrast
- 57 unit tests and a 13-test browser suite (Playwright) that runs against the real
  stack, including automated accessibility checks

### Backend

- FastAPI backend with structured JSON logs, request IDs and one consistent error format
- `/health` (liveness) and `/ready` (database readiness) probes
- PostgreSQL 16 in Docker Compose, schema managed by Alembic migrations
- Registration, login with JWT access tokens, `/me`, and logout that truly revokes the token
- Sign-in protection (Phase 9): limits per network and per account (429 with
  Retry-After), refusal of common passwords, a 1 MiB request limit, security headers, and
  an append-only sign-in history ("Recent sign-ins" in Settings)
- Observability (Phase 9): worker and relay heartbeats, a platform status endpoint, and an
  organization summary with processing times (docs/18)
- API versioning (Phase 9): `/api/v2` employee list with cursor pagination beside the
  unchanged `/api/v1` (docs/08 section 14)
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
- **Reliability engine**: failures are classified; temporary ones (5xx, timeouts, 429) are
  retried with exponential backoff and jitter, honouring `Retry-After`, with a bounded
  number of attempts and every external call recorded in an attempt history
- **Dead-letter queue**: work that fails for good is parked with its error preserved and
  can be replayed (by Integration Managers and Admins) - only the failed steps run again
- **Idempotency keys** in both directions: retried external creates do not create a
  second account (with APIs that honour the key, as the mocks do), and a client resending
  `POST /employees` with the same `Idempotency-Key` gets the first response back
- **Circuit breaker** per connector shared by all workers, optional per-connector **rate
  limits**, and a time limit per operation
- **Audit log**: every important change - employees, permissions, connectors, workflows,
  replays, synchronization outcomes, conflict decisions - is recorded with who did it and
  the request ID, in the same transaction as the change; append-only, enforced by the
  database; no secrets or personal values
- **Optimistic concurrency**: employees carry a version (`ETag`); a save from an outdated
  screen (`If-Match`) is refused with 412 instead of overwriting someone else's change
- **Data conflicts**: per-field source-of-truth policies (HR or a specific application,
  severity, manual or automatic fixing); reconciliation compares each application with
  SyncForge and records differences instead of overwriting them; conflicts are resolved
  explicitly, with override, staleness and permission checks, and a full history
- 579 automated backend tests against a real PostgreSQL database, including two-session
  concurrency tests, connector tests over real HTTP against the mocks, a real Celery
  worker, and failure simulations (outages, 429, timeouts, crashes, duplicates)

## Tech stack

| Layer | Technology | Status |
|---|---|---|
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | in use |
| Database | PostgreSQL 16 (Docker) | in use |
| Containers | Docker images for backend, web (nginx) and mocks; Docker Compose | in use (Phase 10) |
| Auth | Argon2id password hashing, JWT (PyJWT) | in use |
| Integrations | httpx2 (HTTP client), cryptography (Fernet credential encryption) | in use |
| Testing | Pytest, Starlette TestClient | in use |
| Background jobs | Redis 7 (broker), Celery 5.7 (workers) | in use |
| Frontend | Angular 22, TypeScript, Angular CDK, ECharts 6 | in use |
| Frontend testing | Vitest, Playwright, axe-core | in use |
| CI | GitHub Actions (`.github/workflows/ci.yml`) | in use (Phase 10) |

## Run everything in Docker (one command)

Prerequisites: Docker Desktop and Git. From the repository root, after creating `.env`
from `.env.example` (Quick start step 2 below):

```powershell
docker compose --profile full up -d --build
docker compose --profile full ps
```

Open **http://localhost:8080**, create an account and an organization. The API
documentation is at http://localhost:8080/docs. Compose starts PostgreSQL, Redis, a
one-off migration job, the API, a worker, the outbox relay, the three simulated
applications and the web server, in that order, and waits for each to be healthy. Data
is kept in the `postgres-data` volume between runs.

```powershell
docker compose --profile full logs -f worker   # follow one service
docker compose --profile full down             # stop (data kept)
docker compose --profile full down -v          # stop and delete the database volume
```

The containerized API uses the same database as the virtual-environment setup below, so
stop one before starting the other (both use port 5432 and the mock ports 9101-9103).
This is a local setup, not a production deployment.

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

With these four processes and Redis running, the demo injects failures into the mocks and
shows retries, idempotency, the dead-letter queue and replay, the circuit breaker, a rate
limit, a data conflict resolved by policy, a refused stale edit and the audit trail (about
three minutes; [docs/12, section 10](docs/12-reliability-and-retries.md#10-seeing-it-work),
[docs/14, section 9](docs/14-data-integrity.md#9-seeing-it-work)):

```powershell
Set-Location "$HOME\Projects\syncforge"
& "$HOME\Projects\syncforge\backend\.venv\Scripts\python.exe" infrastructure\scripts\demo_reliability.py
```

### Run the web application

Prerequisites: Node.js 22 LTS and npm. With the API running (and, for provisioning, the
mocks, worker and relay above), in another terminal:

```powershell
Set-Location "$HOME\Projects\syncforge\frontend"
npm ci
npm start
```

Open **http://localhost:4200**, create an account, then an organization. The dev server
forwards `/api` to the API on port 8000. Frontend commands and the browser test suite:
[frontend/README.md](frontend/README.md).

Optional - load demo data. Register a user first (for example through `/docs`), then:

```powershell
python -m app.cli seed-demo --admin-email you@example.com
```

This creates the "Acme Demo" organization with 5 departments and 20 fictional employees, and
makes you its Organization Admin.

Maintenance - delete expired revoked tokens and idempotency records (schedule it daily):

```powershell
python -m app.cli purge-expired
```

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

From `frontend/`:

```powershell
npm run test:ci         # unit tests
npx ng lint             # lint, including template accessibility rules
npm run format:check    # formatting
npx ng build            # production build with size budgets
npm run e2e             # browser tests (needs the whole stack running)
```

### Continuous integration

Every push to `main` and every pull request runs `.github/workflows/ci.yml` on GitHub:

| Job | What it does |
|---|---|
| Backend | ruff (backend, mock services, scripts); migrations on an empty PostgreSQL, then `alembic check`; the pytest suite with PostgreSQL and Redis service containers |
| Frontend | ESLint, Prettier, API types against the OpenAPI snapshot, unit tests, production build, `npm audit --omit=dev` |
| Docker stack and browser tests | Builds the three images, starts the whole stack with `docker compose --profile full`, runs the Playwright browser tests against it, and uploads the report if anything fails |

No repository secrets are needed: CI uses throwaway passwords for its own containers and
generates an encryption key per run. Results: the **Actions** tab on GitHub (the badge
at the top of this file shows the latest run on `main`).

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
    reliability/    retry policy, dead letter, circuit breaker, rate limit, idempotency
    integrity/      field comparison rules and default source-of-truth policies
    audit.py        audit log recorder
    workers/        Celery app and tasks
    cli.py          operator commands (create-superadmin, seed-demo, outbox-relay, purge-expired)
    seed.py         demo data
  migrations/       Alembic migrations (0001-0016)
  Dockerfile        one image for the API, worker, relay and migration job
  tests/            pytest suite
docs/               architecture, database, API, security, ADRs
frontend/           Angular application (src/app: core, layout, shared, features; e2e/ browser tests;
                    Dockerfile and nginx.conf for the web container)
mock-services/      mock Slack / Google Workspace / payroll APIs (simulated, failure injection; Dockerfile)
infrastructure/     scripts (demo_reliability.py, benchmark.py)
docker-compose.yml  PostgreSQL and Redis; with --profile full the whole application
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
| [Reliability and retries](docs/12-reliability-and-retries.md) | Failure classification, backoff and jitter, attempt history, dead-letter queue and replay, circuit breaker, rate limits, timeouts, demo |
| [Idempotency](docs/13-idempotency.md) | Where duplicates could come from and what stops each; idempotency keys outgoing and incoming |
| [Data integrity](docs/14-data-integrity.md) | Audit log, optimistic concurrency (ETag / If-Match), source-of-truth policies, reconciliation, conflict resolution |
| [Deployment guide](docs/17-deployment-guide.md) | Local Docker versus production, components, configuration, secrets, database, releases, probes, checklist |
| [Testing strategy](docs/16-testing-strategy.md) | Test layers, principles, where each failure scenario is tested, how to run everything |
| [Phase 9 QA report](docs/PHASE_9_QA_REPORT.md) | Security, versioning, observability and performance work, with all verification results |
| [Performance and scalability](docs/19-performance-and-scalability.md) | Measured latency, throughput and query plans (environment stated), scaling, hot spots |
| [Observability](docs/18-observability.md) | Logs and IDs, heartbeats, system status, organization summary and processing durations, investigating a failure |
| [Security design](docs/15-security-design.md) | Auth flow, JWT lifecycle, passwords, secrets, roles, tenant isolation, connector credentials, SSRF |
| [Troubleshooting](docs/21-troubleshooting.md) | Investigating failed requests and synchronizations, connector, worker, test and Windows issues |
| [Frontend plan](docs/PHASE_8_FRONTEND_PLAN.md) | Screen-to-endpoint map, permission matrix, features the API does not support |
| [Frontend architecture](docs/PHASE_8_FRONTEND_ARCHITECTURE.md) | Layers, routing, session, authorization, state, errors, design system |
| [Frontend components](docs/PHASE_8_FRONTEND_COMPONENTS.md) | Shared components and every page with the API calls behind it |
| [Frontend API integration](docs/PHASE_8_FRONTEND_API_INTEGRATION.md) | Generated types, endpoint map, headers, paging, errors, polling |
| [Frontend testing](docs/PHASE_8_FRONTEND_TESTING.md) | Test layers, browser suite, accessibility findings and results |
| [Phase 8 report](docs/PHASE_8_FRONTEND_REPORT.md) | What was delivered, verification, limitations |
| [Architecture decisions](docs/adr/) | ADR-0001 to ADR-0021 |
| [Project plan](PROJECT_PLAN.md), [Status](PROJECT_STATUS.md), [Changelog](CHANGELOG.md) | Progress tracking |
