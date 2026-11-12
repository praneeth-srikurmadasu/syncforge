# Phase 9 — Security, API versioning, observability and quality assurance: plan

Status: plan, 2026-11-12. Starting point: commit `c209426` (Phase 8 complete; 527 backend
tests, 57 frontend unit tests, 13 browser tests).

## 1. Objectives

1. Close the security gaps the earlier phases recorded as deferred to Phase 9
   (docs/15 section 10, PROJECT_STATUS known limitations).
2. Demonstrate API evolution with a real `/api/v2` endpoint while `/api/v1` keeps working
   unchanged.
3. Make the background system observable: worker and relay health, backlog, processing
   durations, one summary endpoint instead of about 40 dashboard requests.
4. Measure performance on a stated environment with a repeatable script; invent nothing.
5. Run the full quality pass (all test layers, migrations both ways, repeated runs to look
   for the one intermittent failure seen in Phase 5) and write the QA report.

## 2. Audit of the current state

| Area | Today | Gap |
|---|---|---|
| Passwords | Argon2id, minimum 8 | No check against common or breached passwords |
| Login / register | JWT, revocation, constant-time unknown-user path | **No rate limiting**; `email_taken` reveals registered emails |
| Request size | Uvicorn defaults | **No body size limit** |
| Response headers | Request ID, CORS | No `X-Content-Type-Options`, `Cache-Control: no-store` on authenticated responses, framing protection |
| Sign-in auditing | Structured logs only | Login, failed login, logout and lockouts are **not in any audit table** (audit_logs is organization-scoped) |
| CORS | Allow-list from settings, no credentials | Fine; reviewed and documented |
| Health | `/health`, `/ready` (database) | **Worker and relay health unknown** to the API |
| Metrics | Request duration in logs | No processing-duration figures; dashboard needs ~40 `limit=1` calls |
| Versioning | Everything under `/api/v1` | No second version to show how evolution works |
| Performance | Not measured | No numbers |
| Tests | 527 backend (including `alembic check` and a downgrade-to-base / upgrade test), 57 + 13 frontend | Intermittent Phase 5 failure not pinned down; no repeated-run evidence |

## 3. Design decisions

| Decision | Choice | Why |
|---|---|---|
| Rate-limit store | PostgreSQL fixed-window counters (new table), the same pattern as the connector rate limiter (migration 0009) | The API must not depend on Redis to log people in (Redis is a broker here, not a required API dependency); one store to operate. Trade-off: one small write per attempt |
| Rate-limit keys | Per client IP and per account (hash of the normalized email), separately for login and registration | Per-IP alone is beaten by many IPs; per-account alone locks out users through someone else's IP. Both, with `429` and `Retry-After` |
| Client IP behind a proxy | Taken from the ASGI client address; proxies are trusted only through Uvicorn's `--forwarded-allow-ips` | Never trust `X-Forwarded-For` from anyone |
| Weak-password check | Offline list of the 10,000 most common passwords (SecLists, MIT licence) bundled with the backend, plus context words (the email's local part, "syncforge") | NIST SP 800-63B blocklist check without sending anything to a third party. Trade-off: not a full breach corpus |
| Body size | 1 MiB default (`MAX_REQUEST_BODY_BYTES`), enforced in ASGI middleware while streaming, `413 payload_too_large` | Largest legitimate body today is a connector config of a few kB |
| Sign-in audit | New append-only table `security_events` (not organization-scoped; enforced by a trigger like audit_logs). Users see their own recent sign-ins; Super Admins see all | Sign-ins happen before an organization is chosen, so they cannot go in `audit_logs` without weakening its tenant model |
| Component health | Worker and relay write heartbeats to a `component_heartbeats` table; `/ready` stays database-only; a Super Admin `GET /api/v1/system/status` reports heartbeats, outbox backlog and stuck events | Readiness must not fail the API because a worker is down (events wait in the outbox), but operators must see it |
| Dashboard figures | `GET /api/v1/organizations/{org}/summary`: counts plus processing durations (p50 / p95 over 24 h, from event timestamps) in one request; the frontend dashboard switches to it | Replaces ~18 total requests; durations become visible. The 7-day audit windows stay as they are |
| API v2 | `GET /api/v2/organizations/{org}/employees` with keyset (cursor) pagination and a `data` / `page` envelope; v1 untouched | Shows a real breaking change (pagination model) shipped as a new version, with a documented migration path |
| Metrics format | JSON from the summary and status endpoints; no Prometheus exporter | No new dependency; an exporter is a Phase 10 / future option and is documented as such |

## 4. Milestones

| # | Scope | Main files |
|---|---|---|
| 1 | This plan | `docs/PHASE_9_PLAN.md` |
| 2 | Security controls: login / register rate limits, common-password check, body size limit, security headers; frontend shows 429 with the wait time | `app/security/rate_limit.py`, `app/security/password_policy.py`, `app/security/common_passwords.txt`, `app/core/middleware.py`, `app/services/auth.py`, migration 0013, tests; frontend login / register |
| 3 | Security events: append-only table, recording from the auth service, `GET /api/v1/auth/activity` (own), `GET /api/v1/security-events` (Super Admin); "Recent sign-ins" in Settings | migration 0014, `app/models/security_event.py`, service, router, tests; frontend settings |
| 4 | Observability: heartbeats from worker and relay, `GET /api/v1/system/status`, organization summary with processing durations, durations in worker logs; dashboard uses the summary | migration 0015, `app/monitoring/`, routers, tests; frontend dashboard |
| 5 | `/api/v2` employees with cursor pagination; version headers; OpenAPI; docs on compatibility and migration | `app/api/v2/`, tests, docs/08 |
| 6 | Performance: `infrastructure/scripts/benchmark.py` (API latency percentiles, event throughput, `EXPLAIN ANALYZE` of key queries); results with environment and method | script, `docs/19-performance-and-scalability.md` |
| 7 | QA: all suites, repeated backend runs, migration downgrade / upgrade check, browser suite, security review checklist; QA report; docs 15, 16, 18, 21, status, changelog | `docs/PHASE_9_QA_REPORT.md` and docs |

## 5. Acceptance criteria

- Repeated failed logins for one account, or many logins from one IP, get `429` with
  `Retry-After`; a correct password after the window passes works again. Tested.
- Registration refuses passwords on the common list or containing the email name. Tested.
- A body over the limit gets `413` before the handler runs. Tested.
- Every login, failed login, logout and rate-limit refusal is a `security_events` row
  without passwords or tokens; the table refuses UPDATE and DELETE. Tested.
- Stopping the worker or relay shows as stale in `/system/status` within the heartbeat
  timeout. Tested with a stopped process in the workspace.
- The summary endpoint's counts equal the list endpoints' totals. Tested.
- `/api/v2/.../employees` pages through all employees with cursors, no duplicates or gaps
  under inserts; `/api/v1` responses are byte-for-byte unchanged in shape. Tested.
- Benchmarks run from one command and their output is recorded with the environment.
- All test layers pass, including the existing migration round-trip test with the new migrations.
- No backend behaviour from Phases 2–8 changes except where listed here.
