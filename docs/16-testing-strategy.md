# 16 - Testing strategy

How SyncForge is tested, what each layer proves, how to run it, and where each required
failure scenario is covered. Counts are from 2026-11-13 (end of Phase 9). Results of the
quality pass are in [PHASE_9_QA_REPORT.md](PHASE_9_QA_REPORT.md).

## 1. Layers

| Layer | Tool | Where | Count | Runs against |
|---|---|---|---|---|
| Backend unit, integration and API | pytest, FastAPI TestClient | `backend/tests/` (37 files) | 579 | A real PostgreSQL 16 (`syncforge_test` database) |
| Connector adapters over HTTP | pytest + the mock services as real HTTP servers | `test_connector_adapters.py`, `test_connectors_api.py` | included above | Slack, Google Workspace and payroll mocks on local ports |
| Worker and relay end to end | pytest with a real Celery worker and Redis | `test_celery_worker.py` | included above | Redis 7 |
| Schema | Alembic | `test_migrations.py` | included above | `alembic check` (models equal migrations) and downgrade to base / upgrade to head |
| Frontend unit and component | Vitest via `ng test` | `frontend/src/**/*.spec.ts` (17 files) | 60 | jsdom, HTTP mocked with `HttpTestingController` |
| Browser end to end | Playwright 1.65 | `frontend/e2e/tests/` (6 files) | 13 | The whole running stack, Chromium |
| Accessibility | axe-core in Playwright | `quality.spec.ts` | 14 pages x 2 themes | WCAG 2 A/AA, serious and critical issues |
| Performance | `infrastructure/scripts/benchmark.py` | - | - | The running stack (docs/19) |
| Static checks | ruff (lint, format), ESLint with angular-eslint template rules, Prettier, TypeScript strict | all code | - | - |
| API contract | `npm run api:check` | `frontend/openapi/openapi.json` | - | Generated types equal the committed snapshot |

## 2. Principles

- **Real database, not mocks.** Constraints, triggers (append-only audit and security
  events), row locks, `SKIP LOCKED`, `ON CONFLICT` and percentile queries are part of the
  behaviour, so tests run on PostgreSQL. Each test runs inside a transaction that is
  rolled back (`conftest.py`), so tests are independent and the database stays clean.
- **Real HTTP to the mocks.** Adapter tests call the mock services over sockets, so
  timeouts, status codes, `Retry-After` and idempotency keys behave as on the wire. Faults
  are injected through the mocks' `/_mock/faults` API.
- **Concurrency is tested with two sessions.** Where correctness depends on locking, the
  test opens two database sessions and races them (simultaneous saves, replays, demotions,
  manager changes, duplicate idempotent requests).
- **Behaviour, not implementation.** Tests assert what a client or operator observes:
  status codes, error codes, rows written, external accounts created once, log lines
  without secrets.
- **Security properties are tested as assertions.** For example: no password, token or
  credential appears in logs, audit records or security events; cross-organization access
  gives 404 on every endpoint.
- **Browser tests provision their own tenants** through the API, so they never depend on
  each other or on existing data.

## 3. Required scenarios and where they are tested

| Scenario | Tests |
|---|---|
| Create employee -> event -> asynchronous processing -> accounts in mock Slack and Google -> success | `test_onboarding_creates_accounts_in_every_application`, `test_relay_to_worker_onboarding_and_duplicate_delivery`; browser: "build and activate an onboarding workflow, then a hire is provisioned" |
| External failure -> retry -> retries exhausted -> dead letter -> replay -> completed | `test_a_transient_failure_is_retried_after_a_backoff_and_then_succeeds`, `test_exhausted_retries_park_the_event_with_its_error_preserved`, `test_replay_reruns_only_what_failed_and_completes`; browser: "a failing step is dead-lettered, then replayed to completion" |
| Duplicate event delivery | `test_duplicate_delivery_is_skipped_and_creates_nothing_twice`, `test_relay_to_worker_onboarding_and_duplicate_delivery` |
| HTTP 429 and `Retry-After` | `test_rate_limit_carries_retry_after`, `test_rate_limit_waits_at_least_retry_after`, `test_retry_after_is_respected_but_capped` |
| External API timeout | `test_slow_responses_time_out`, `test_timeouts_are_retried`, `test_a_timed_out_create_is_retried_safely`, `test_one_operation_cannot_exceed_its_deadline_across_requests` |
| Invalid or expired OAuth / connector credentials | `test_wrong_credentials_are_an_authentication_error`, `test_google_gets_a_new_token_when_the_old_one_expires`; browser: a wrong Slack token fails the connection test |
| Concurrent updates | `test_simultaneous_saves_from_the_same_version_let_exactly_one_win`, `test_simultaneous_replays_of_one_entry_replay_it_once`, `test_simultaneous_manager_changes_cannot_form_a_cycle`, `test_simultaneous_demotions_cannot_remove_every_admin`; browser: concurrent edit shows 412 and "load latest" |
| Unauthorized access | `test_requires_authentication`, `test_me_with_expired_token_returns_401`, `test_logout_revokes_the_token`, `test_viewers_can_read_but_not_manage`; browser: viewer RBAC |
| Cross-organization access | `test_cross_organization_access_is_404_everywhere`, `test_list_never_includes_other_organizations`, `test_cannot_use_another_organizations_manager`, v2 `test_organization_isolation_and_cursor_scope`; browser: "an organization the user does not belong to is not shown" |
| Worker crash | `test_a_crashed_worker_is_resumed_without_repeating_finished_work`, `test_relay_recovery_hands_a_crashed_workers_event_to_the_next_worker` |
| Transactional outbox | `test_employee_change_and_its_events_share_one_transaction`, `test_outbox_relay.py` |
| Circuit breaker | `test_circuit_breaker.py` (closed -> open -> half-open -> closed) |
| Data conflict detected and resolved | `test_conflicts.py`; browser: "a department changed in payroll becomes a conflict that is resolved" |
| Sign-in abuse (Phase 9) | `test_security_hardening.py`, `test_security_events.py` |

## 4. Running the tests

Backend (PostgreSQL running; from `backend/`):

```powershell
& "$HOME\Projects\syncforge\backend\.venv\Scripts\python.exe" -m ruff check .
& "$HOME\Projects\syncforge\backend\.venv\Scripts\python.exe" -m ruff format --check .
& "$HOME\Projects\syncforge\backend\.venv\Scripts\python.exe" -m pytest -q
```

The suite creates and migrates the `syncforge_test` database itself; the worker test
needs Redis; the adapter tests start the mock services in-process.

Frontend (from `frontend/`):

```powershell
npm run test:ci
npx ng lint
npm run format:check
npm run api:check
npx ng build
npm run e2e            # needs the whole stack running (frontend/README.md)
```

## 5. Continuous integration

`.github/workflows/ci.yml` runs on every push to `main`, on pull requests and on demand:

1. **Backend:** ruff on the backend, mock services and scripts; `alembic upgrade head` on
   an empty database followed by `alembic check`; the full pytest suite with PostgreSQL 16
   and Redis 7 as service containers.
2. **Frontend:** lint, formatting, API-type check, unit tests, production build,
   `npm audit --omit=dev`.
3. **Docker stack and browser tests** (after 1 and 2 pass): builds the images, starts the
   whole stack with Docker Compose (profile `full`), waits for `/ready` through nginx,
   and runs the 13 Playwright tests against the containers (`SF_WEB`, `SF_API`,
   `SF_PAYROLL_MOCK` point at port 8080 and the payroll mock). On failure it prints the
   service logs and uploads the Playwright report.

No secrets are stored in the repository or in GitHub: the containers get throwaway
passwords and a per-run encryption key.

## 6. Flaky tests

Policy: a test that fails intermittently is treated as a bug (in the test or the code)
and investigated, never retried until green. The suite has no automatic reruns.

The single unexplained failure seen at the end of Phase 5 (1 of 15 runs, name not
captured) has not reappeared since. In the Phase 9 quality pass the backend suite ran
5 times in its normal order and 3 times in random order (pytest-randomly installed
temporarily, seeds 1111, 2222, 3333), 576 tests each time, all passing. The browser suite
ran twice in a row, 13 of 13 each time. Earlier browser-test flakiness (ambiguous
selectors, waiting for rows) was fixed in Phase 8 by scoping selectors and waiting for
the expected state.

## 7. What is not covered

- Load and concurrency limits of the API (benchmarks are sequential; docs/19).
- Real Slack and Google tenants (all connectors are tested against the local mocks).
- Browsers other than Chromium; a recorded manual screen-reader pass.
