# SyncForge - Final engineering report

**Date:** 2026-11-13. **Scope:** Phases 1-10. **Repository:**
https://github.com/praneeth-srikurmadasu/syncforge (private). **Licence:** MIT.

This report summarizes what was built and what it was checked against. Every figure here
was measured or counted. The design details are in the numbered documents in `docs/`, and
this report links to them instead of repeating them.

---

## 1. Project overview

SyncForge keeps employee data consistent across the applications a company uses. A
change to an employee (hire, transfer, new manager, termination) becomes an event. A
background worker processes the event by running the organization's workflows: for
example, create the Slack account, then the Google Workspace account, then the payroll
record. Failures are retried, then parked in a dead-letter queue for an administrator to
replay. Disagreements between SyncForge and an external application are opened as
conflicts and resolved by configurable source-of-truth policies, never by silent
overwrites. Every important action is written to an append-only audit log.

More detail: [01 - Project overview](01-project-overview.md), [02 - Requirements](02-requirements.md).

## 2. Architecture summary

SyncForge is a modular monolith ([ADR-0001](adr/0001-modular-monolith-with-fastapi.md))
with background processes that scale independently:

| Process | Role |
|---|---|
| API (FastAPI, uvicorn) | REST API: authentication, organizations, employees, connectors, workflows, events, reliability, conflicts, audit |
| Worker (Celery, one or more) | Claims events and runs workflow steps against connectors |
| Outbox relay | Publishes committed outbox rows and due retries to Redis |
| PostgreSQL 16 | System of record, including events, outbox, attempts, breaker and rate-limit state |
| Redis 7 | Broker only. Losing a message is recovered from PostgreSQL. |
| Simulated applications | Local Slack, Google Workspace and payroll services with failure injection |
| Web (Angular, served by nginx in Docker) | The administration application |

An API request writes the employee change, the event and an outbox row in **one
transaction** ([ADR-0012](adr/0012-transactional-outbox.md)). Delivery is at least once,
and every consumer is idempotent: a conditional claim with a lease, per-step results, and
idempotency keys on external creates. SyncForge does not claim exactly-once delivery.

Diagrams: [05 - System architecture](05-system-architecture.md). Section 9 of that
document indexes every required diagram, and all 32 Mermaid diagrams in the
documentation were rendered with mermaid-cli 11.16.0 without errors.

## 3. Technology stack

| Layer | Choice (pinned) |
|---|---|
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2 (synchronous, [ADR-0003](adr/0003-synchronous-sqlalchemy.md)), Alembic |
| Background work | Celery with Redis as the broker ([ADR-0010](adr/0010-redis-and-celery-for-background-work.md)) |
| Database | PostgreSQL 16 |
| Frontend | Angular 22 (standalone components, signals), TypeScript, RxJS, Angular CDK, ECharts, custom design system |
| Tests | pytest (on real PostgreSQL), Vitest via the Angular builder, Playwright with axe-core |
| Delivery | Docker, Docker Compose (profile `full`), GitHub Actions |

Exact versions: `backend/requirements*.txt`, `frontend/package.json` (lock file committed).

## 4. Implemented features

- **Identity and tenancy:** registration, sign-in with JWT, logout that revokes the token
  (denylist), four roles, organization membership checked on every organization route,
  and composite foreign keys so rows cannot reference another tenant
  ([ADR-0005](adr/0005-organization-level-data-isolation.md),
  [ADR-0006](adr/0006-composite-foreign-keys-for-tenant-integrity.md)).
- **Employees:** CRUD with archive, departments, reporting lines (cycle-safe under an
  advisory lock), search, filters, pagination, lifecycle events (`employee.created`,
  `.updated`, `.department_changed`, `.manager_changed`, `.terminated`), and optimistic
  concurrency with ETag and If-Match.
- **Connectors:** a common adapter interface, encrypted credentials (Fernet), connection
  tests, health, error normalization, timeouts, an SSRF host allowlist, and versioned
  connector types. Slack, Google Workspace and payroll are implemented. **All three run
  against local simulated services** (see section 7).
- **Workflows:** configurable triggers and ordered steps, activation and deactivation,
  execution history, and per-step status.
- **Event processing:** persisted events, transactional outbox, relay, workers with
  lease-based claims, and correlation IDs carried through the logs.
- **Reliability:** exponential backoff with jitter, failure classification (retryable or
  permanent), `Retry-After`, per-connector rate limits, a shared circuit breaker, an
  operation deadline, idempotency keys, a dead-letter queue with authorized replay, and
  reconciliation.
- **Data integrity:** field-level source-of-truth policies, conflict detection with
  severity, policy-aware resolution (an override is required to go against policy), and
  conflict history.
- **Audit and security:** append-only audit log, append-only sign-in history, sign-in
  rate limits, common-password refusal, a request body limit, and security headers.
- **Observability:** JSON logs with request, correlation and event IDs, `/health` and
  `/ready`, worker and relay heartbeats, platform status, and an organization summary
  with processing-time percentiles.
- **API versioning:** a `/api/v2` employee list with keyset (cursor) pagination beside
  the unchanged v1.
- **Web application:** all 16 required areas, including dashboard, employees,
  connectors, workflows, events, reliability, dead-letter queue, conflicts, policies,
  audit log, team, settings, and a "Developer API" card linking the interactive API
  reference. It has role-aware navigation, light and dark themes, and phone layouts.

The full requirement-by-requirement evidence (test names per requirement) is in
[03 - Functional requirements](03-functional-requirements.md) and
[04 - Non-functional requirements](04-non-functional-requirements.md).

## 5. Database design

There are 27 tables, created by 16 Alembic migrations (0001-0016). Every migration
downgrades, and `alembic check` reports no drift between the models and the schema.

| Area | Tables |
|---|---|
| Identity | organizations, users, organization_memberships, revoked_tokens, auth_rate_windows, security_events |
| Workforce | departments, employees |
| Connectors | connectors, connector_credentials, external_accounts, connector_circuits, connector_rate_windows |
| Workflows and events | workflows, workflow_steps, integration_events, outbox_events, workflow_executions, synchronization_jobs, synchronization_attempts |
| Reliability | idempotency_records, dead_letter_events |
| Integrity and audit | data_source_policies, data_conflicts, conflict_resolutions, audit_logs |
| Monitoring | component_heartbeats |

ER diagram, columns, constraints, indexes, transaction boundaries and retention notes:
[07 - Database design](07-database-design.md).

## 6. API inventory

The OpenAPI document has 58 operations. It is served at `/docs` (Swagger UI), `/redoc`
and `/openapi.json`, and the committed copy is checked against the frontend types in CI.

| Group | Operations |
|---|---|
| `/health`, `/ready` | 2 |
| `/api/v1/auth` (register, login, me, logout, activity) | 5 |
| `/api/v1/organizations` (create, list, get, members) | 4 |
| `/api/v1/organizations/{id}/...` (employees, departments, connectors, workflows, events, executions, dead-letter events, reliability, conflicts, policies, audit logs, summary) | 43 |
| `/api/v1/connector-types`, `/api/v1/security-events`, `/api/v1/system/status` | 3 |
| `/api/v2/organizations/{id}/employees` | 1 |

Contracts, error codes, pagination and idempotency behaviour:
[08 - API design](08-api-design.md).

## 7. Connector implementation status

| Connector | Status |
|---|---|
| Slack (SCIM-style users API) | **Simulated.** Implemented against a local mock service. A real workspace needs a Slack plan with SCIM and a token. |
| Google Workspace (Directory API) | **Simulated.** Implemented against a local mock service. A real tenant needs a service account with domain-wide delegation (JWT-bearer grant). |
| Payroll | **Simulated by design.** Mock payroll system. |

No real external tenant was used at any point. What a real integration still needs is in
[10 - Connector framework](10-connector-framework.md), section 1.

## 8. Event-processing design

`API transaction (employee + event + outbox)` → `relay publishes event ID to Redis` →
`worker claims the event (conditional UPDATE with a lease)` → `workflows matched by
trigger` → `steps run in order; each attempt recorded` → `event completed, retrying, or
dead_letter`.

A worker that crashes leaves an expired lease, and the next claim resumes at the
unfinished step. Steps that already succeeded are skipped.
[09 - Event-driven architecture](09-event-driven-architecture.md),
[11 - Workflow engine](11-workflow-engine.md).

## 9. Reliability mechanisms

| Mechanism | Behaviour |
|---|---|
| Retries | 5 attempts by default. The delay is base 2 s, doubling, ±20% jitter, capped at 300 s. Permanent failures (validation, authentication, authorization, conflict) are not retried. |
| Rate limits | An HTTP 429 `Retry-After` is honoured. The per-connector limit in a one-minute window delays steps without using an attempt. |
| Circuit breaker | Opens after 5 consecutive failures for 60 s, then lets one trial call through (half-open). State is shared by all workers. |
| Timeouts | Connect 3 s, read 10 s, operation deadline 30 s. |
| Idempotency | Event claims, per-job results, `Idempotency-Key` on `POST /employees`, and `syncforge-job-<id>` keys on external creates. |
| Dead-letter queue | The original error is kept. Replay requires the Integration Manager role or higher and is audited. |

[12 - Reliability and retries](12-reliability-and-retries.md),
[13 - Idempotency](13-idempotency.md).

## 10. Security measures

- Passwords are hashed with Argon2id (pwdlib). The policy requires at least 8 characters and refuses
  2,087 common passwords.
- JWTs are HS256, expire after 30 minutes, and logout revokes them server-side.
- Roles are checked in the services, and organization isolation is enforced in queries
  and by composite foreign keys.
- Connector credentials are encrypted with Fernet and never returned or logged. The audit
  log records values only for an allowlist of non-personal employee fields.
- Sign-in is limited per network and per account (429 with Retry-After). Requests have a
  1 MiB body limit, the API sends CSP and `no-store` headers, and CORS is an explicit
  allowlist.
- Only `.env.example` with placeholders is committed. CI uses throwaway values.

The review of each item, with risks and mitigations, is in
[15 - Security design](15-security-design.md), section 11.

## 11. Testing results (actual)

### Clean-machine verification (2026-11-13, Linux workspace)

A fresh `git clone` of GitHub `main` at `0784cd1` (the last pushed commit before this
milestone, which adds documentation and the licence only). The README steps were followed
on empty databases.

| Step | Result |
|---|---|
| `.env` from `.env.example` with a generated JWT secret and Fernet key | Done |
| `pip install -r requirements-dev.txt` (Python 3.13.18) | Installed |
| `alembic upgrade head` → `downgrade base` → `upgrade head` → `alembic check` | 0016 (head), no drift |
| `ruff check`, `ruff format --check` | All checks passed, 173 files formatted |
| `pytest` | **579 passed** (95.8 s) |
| API, simulated applications, worker, relay started; `/health`, `/ready`, `/docs` | ok, ready (database ok), 200 |
| `infrastructure/scripts/demo_reliability.py` | Exit 0. Retries, dead-letter and replay, circuit breaker, rate limit, conflict, 412 stale edit and audit trail all as documented. |
| `npm ci` (Node 22.23.4), `lint`, `format:check`, `api:check` | Clean; API types match `openapi.json` |
| Unit tests | **60 passed** (17 files) |
| `npm run build` | Bundle generated |
| Playwright browser suite against the running stack | **13 passed** (3.6 min) |

### Docker and CI

- **Docker:** on the owner's Windows machine (commit `f30cf29`),
  `docker compose --profile full up -d --build` built the three images and started every
  service, and the API was healthy. Docker Hub is not reachable from the build workspace,
  so containers were run on Windows and in CI only.
- **GitHub Actions:** CI run #2 (commit `3e9fe33`) passed all three jobs: backend,
  frontend, and the Docker stack with the browser tests running against the containers.
  Runs #1 and #3 ended when a newer push arrived. The workflow cancels runs still in
  progress for the same branch.

Test layers and what each one covers: [16 - Testing strategy](16-testing-strategy.md).

## 12. Performance results

These were measured with `infrastructure/scripts/benchmark.py` in the 2-CPU Linux
workspace, with everything on one machine. The raw JSON is in `docs/performance/`.

- API p50 latency: 8-17 ms at 1,000 employees. At 10,000 employees the OFFSET last page
  is 27.6 ms, while the v2 cursor last page is 9.9 ms.
- Throughput: one worker processed 9.5-10.2 events/s (3 external calls each). Two
  workers processed 16.3 events/s. All 300 events completed.
- The measurements led to migration 0016, which made every cursor page an index scan
  that reads 20 rows.

Method and limitations (a shared machine, local mocks, not a production benchmark):
[19 - Performance and scalability](19-performance-and-scalability.md).

## 13. Case studies

[24 - Case studies](24-case-studies.md) covers all ten scenarios with the code paths and
tests that verify them:

1. Onboarding.
2. Department transfer.
3. Termination.
4. Slack unavailable.
5. Google 429.
6. Duplicate delivery.
7. Conflicting department.
8. Worker crash.
9. Expired credentials.
10. Dead-letter replay.

## 14. Known limitations

**Integrations**
- All three connectors are simulated and were verified against local mocks only. Real
  Slack and Google need real tenants and, for Google, the JWT-bearer grant (docs/10,
  section 1).
- OAuth tokens are cached per process. The browser authorization-code flow is not
  implemented.
- The mocks honour idempotency keys, but the real Slack SCIM and Google Directory APIs do
  not document such a header. Against them, a crash between the external create and
  storing the link produces a `conflict` and a dead-letter entry: visible, not a silent
  duplicate. "Find before create" (adopting an existing account by email) is not
  implemented (docs/13, section 3).
- The SSRF allowlist matches host names, not resolved IP addresses.

**Processing and reliability**
- A long outage dead-letters work after the retry budget: about 30 s of backoff, longer
  with `Retry-After` or an open circuit. The entries are then replayed one at a time,
  because there is no bulk replay.
- Circuit-breaker and rate-limit state are PostgreSQL rows, updated on every external
  call. That is fine at provisioning volumes. The rate limit is a fixed one-minute
  window, so up to twice the limit can pass across a window boundary.
- Several workers do not guarantee per-employee ordering. Steps read the current state,
  so this is safe today.
- Reconciliation runs on demand or on the operator's schedule, covering up to 500
  accounts and seven fields per run. Conflicts are found when it runs, not instantly.

**Data and retention**
- Event, outbox, execution, attempt, dead-letter, audit and conflict history are never
  pruned. `python -m app.cli purge-expired` (for expired revoked tokens and
  idempotency records) must be scheduled by the operator; SyncForge has no built-in scheduler.
- Optimistic concurrency covers employees. Clients that send no `If-Match` still get
  last-write-wins (the web application always sends it).
- Termination is final. Rehiring means creating a new employee record.
- Substring search and the organization summary read the whole organization. They take
  38-40 ms at 10,000 employees on the 2-CPU test machine (options in docs/19, section 5).

**Access**
- Members can be added only after they have registered. There are no email invitations.
- Passwords need at least 8 characters and pass a common-password check: a bundled list
  of 2,087 entries, not a full breach corpus. There is no MFA. NIST SP 800-63B-4
  recommends 15 or more characters when a password is the only factor.
- There are no refresh tokens, so users sign in again after 30 minutes. The browser keeps
  the bearer token in `sessionStorage`, not in an HttpOnly cookie.

**Testing and deployment**
- One unidentified intermittent backend test failure was seen once, at the end of
  Phase 5 (1 of 15 full runs, test name not captured). It has not reappeared: the suite
  passed 5 times in order and 3 times in random order in the Phase 9 quality pass, and
  again in the clean-clone run.
- Browser tests run in Chromium only. No full manual screen-reader pass has been
  recorded.
- The Docker Compose setup is for local use and is not a production deployment.

## 15. Deployment instructions

- **Local, one command:** `docker compose --profile full up -d --build`, then open
  http://localhost:8080 (README, "Run everything in Docker").
- **Local development:** a virtual environment, Angular dev server, worker and relay
  (README, "Quick start").
- **Production guidance:** [17 - Deployment guide](17-deployment-guide.md) covers the
  reference architecture, secrets and key rotation, database roles, pooling, TLS,
  backups, expand-and-contract migrations, probes, logging and a checklist.

## 16. Git history

GitHub `main` has 48 commits, from `f476de2` (2026-11-11, environment set-up) to
`0784cd1` (2026-11-13, case studies and interview preparation). The commits follow the
conventional prefixes (`feat`, `fix`, `docs`, `test`, `perf`, `build`, `ci`, `chore`),
one or more per milestone. The last two commits add this report and the licence, then
remove the working documents. See `git log --oneline`.

## 17. GitHub publication

The repository is private and already pushed. Each push was made by the owner after
review, and the GitHub contents were compared file-by-file with the verified copy after
each push. To make the repository public, go to GitHub → Settings → General → Danger Zone
→ Change visibility. Before doing that:

- Run a final secrets scan, for example `git log -p | Select-String -Pattern "SECRET|PASSWORD|KEY="`.
  Only placeholders and test values should appear.
- Confirm the README badges and screenshots render.

## 18. Future engineering improvements

The top items from [23 - Future improvements](23-future-improvements.md):

- Real tenant verification for Slack and Google, with the OAuth authorization-code flow.
- "Find before create" adoption of existing accounts.
- Bulk dead-letter replay.
- Retention jobs for event tables.
- Parallel workflow steps (a DAG).
- Per-employee ordering keys.
- Sliding-window rate limits.
- Metrics export (Prometheus or OpenTelemetry).
- Full-text search.

## 19. Interview presentation guide

[22 - Interview preparation](22-interview-preparation.md) contains:

- a timed 10-15 minute walkthrough;
- 21 topics, each with an explanation, why SyncForge needs it, where it is in the code, a
  scenario, alternatives, trade-offs, questions, and sample answers;
- general questions.

Suggested live demo order:

1. Dashboard.
2. Add an employee and watch the event complete.
3. Inject a failure into a mock and show the retries, the dead-letter entry and the
   replay.
4. Open a conflict and resolve it by policy.
5. Show the audit trail.
