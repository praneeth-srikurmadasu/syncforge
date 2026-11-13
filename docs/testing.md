# Testing

| Layer | Tool | Count | Runs against |
|---|---|---|---|
| Backend unit, integration and API | pytest, FastAPI TestClient | 579 tests, 37 files | A real PostgreSQL 16 (`syncforge_test`) |
| Connector adapters | pytest with the mock services as real HTTP servers | included above | Slack, Google and payroll mocks on local ports |
| Worker end to end | pytest with a real Celery worker | included above | Celery's in-memory broker: relay → broker → worker → engine → mocks |
| Schema | Alembic | included above | `alembic check`, plus downgrade to base and upgrade to head |
| Frontend unit and component | Vitest via `ng test` | 60 tests, 17 files | jsdom, HTTP mocked with `HttpTestingController` |
| Browser end to end | Playwright | 13 tests | The whole running stack, Chromium |
| Accessibility | axe-core in Playwright | 14 pages × 2 themes | WCAG 2 A/AA, serious and critical issues |
| Static checks | ruff, ESLint with template accessibility rules, Prettier, strict TypeScript | all code | |
| API contract | `npm run api:check` | | The generated frontend types equal the committed OpenAPI snapshot |

## Principles

- **A real database, not mocks.** Constraints, triggers, row locks, `SKIP LOCKED`,
  `ON CONFLICT` and percentile queries are part of the behaviour, so the tests use
  PostgreSQL. Each test runs in a transaction that is rolled back.
- **Real HTTP to the mocks.** Timeouts, status codes, `Retry-After` and idempotency keys
  behave as they do on the wire. Faults are injected through the mocks' `/_mock/faults`
  API.
- **Concurrency is tested with two sessions.** Where correctness depends on locking, the
  test opens two database sessions and races them.
- **Security properties are assertions.** Examples: no password, token or credential
  appears in logs, audit records or security events, and cross-organization access gives
  404 on every endpoint.
- **Flaky tests are bugs.** There are no automatic reruns. The backend suite passed 5
  times in order and 3 times in random order, and the browser suite twice in a row.

## Key scenarios

| Scenario | Tests |
|---|---|
| Hire → event → worker → accounts in the Slack and Google mocks | `test_onboarding_creates_accounts_in_every_application`, `test_relay_to_worker_onboarding_and_duplicate_delivery`; browser: a hire is provisioned |
| Failure → retries → dead letter → replay → completed | `test_a_transient_failure_is_retried_after_a_backoff_and_then_succeeds`, `test_exhausted_retries_park_the_event_with_its_error_preserved`, `test_replay_reruns_only_what_failed_and_completes`; browser: dead-letter replay |
| Duplicate event delivery | `test_duplicate_delivery_is_skipped_and_creates_nothing_twice` |
| HTTP 429 and `Retry-After` | `test_rate_limit_waits_at_least_retry_after`, `test_retry_after_is_respected_but_capped` |
| External API timeout | `test_timeouts_are_retried`, `test_a_timed_out_create_is_retried_safely`, `test_one_operation_cannot_exceed_its_deadline_across_requests` |
| Invalid or expired credentials | `test_wrong_credentials_are_an_authentication_error`, `test_google_gets_a_new_token_when_the_old_one_expires` |
| Worker crash | `test_a_crashed_worker_is_resumed_without_repeating_finished_work`, `test_relay_recovery_hands_a_crashed_workers_event_to_the_next_worker` |
| Transactional outbox | `test_employee_change_and_its_events_share_one_transaction` |
| Concurrent updates | `test_simultaneous_saves_from_the_same_version_let_exactly_one_win`, `test_simultaneous_replays_of_one_entry_replay_it_once`, `test_simultaneous_manager_changes_cannot_form_a_cycle` |
| Unauthorized and cross-organization access | `test_requires_authentication`, `test_logout_revokes_the_token`, `test_cross_organization_access_is_404_everywhere`; browser: viewer and isolation |
| Data conflict detected and resolved | `test_conflicts.py`; browser: payroll department conflict |

## Running the tests

```bash
# Backend: PostgreSQL running (docker compose up -d postgres); from backend/
ruff check . && ruff format --check .
pytest -q

# Frontend: from frontend/
npm run test:ci && npx ng lint && npm run format:check && npm run api:check && npx ng build
npm run e2e        # needs the whole stack running (frontend/README.md)
```

The suite creates and migrates the `syncforge_test` database itself, and the adapter
tests start the mock services in-process.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main`, on pull requests and on demand:
1. **Backend:**
   - ruff;
   - migrations on an empty database, followed by `alembic check`;
   - the full pytest suite, with PostgreSQL 16 and Redis 7 as service containers.
2. **Frontend:** lint, formatting, the API-type check, unit tests, a production build, and
   `npm audit --omit=dev`.
3. **Docker stack and browser tests:**
   - build the images and start the full stack with Docker Compose;
   - wait for `/ready` through nginx, then run the 13 Playwright tests against the
     containers;
   - on failure, print the service logs and upload the Playwright report.

CI uses throwaway passwords and a per-run encryption key. No secrets are stored.

## Not covered

- API load limits. The benchmarks are sequential ([performance](performance.md)).
- Real Slack and Google tenants.
- Browsers other than Chromium, and a manual screen-reader pass.
