# Phase 9 - Quality assurance and completion report

Phase 9: security hardening, API versioning, observability and performance, closed by a
quality pass. Every result below was produced by an actual run; the date and environment
are stated. Plan and acceptance criteria: [PHASE_9_PLAN.md](PHASE_9_PLAN.md).

## 1. What Phase 9 delivered

| # | Milestone | Main result | Commit |
|---|---|---|---|
| 1 | Audit and plan | `docs/PHASE_9_PLAN.md` | `b0fb664` |
| 2 | Security controls | Sign-in limits per IP and per account, registration limit (429 + `Retry-After`, PostgreSQL counters, hashed subjects, migration 0013); common-password refusal; 1 MiB body limit; security headers; CORS headers for `If-Match` / `Idempotency-Key` | `b0fb664` |
| 3 | Security events | Append-only `security_events` (migration 0014); `GET /auth/activity`; `GET /security-events` (Super Admins); "Recent sign-ins" in Settings | `b2af557` |
| 4 | Observability | Worker and relay heartbeats (migration 0015), `GET /system/status`, `GET .../summary` with processing durations, delivery duration log line; dashboard requests 48 -> 33; `docs/18` | `ec8cf49` |
| 5 | API versioning | `GET /api/v2/.../employees` with keyset pagination and checked cursors; v1 unchanged; versioning policy and migration guide; ADR-0021 | `7fa35a1` |
| 6 | Performance | `benchmark.py`, measured results, `docs/19`; employee sort index widened (migration 0016) after the measurements | `11aaa1c` |
| 7 | Quality pass | This report, `docs/16-testing-strategy.md`, security review (docs/15 section 11), CORS tests, troubleshooting entries | this commit |

API: 58 operations (53 at the end of Phase 8), all in the OpenAPI document; the
frontend's snapshot equals the live document. Database: migrations 0013-0016.

## 2. Test results (Linux workspace, 2026-11-13)

Environment: Intel Xeon 2.10 GHz, 2 logical CPUs, 7.8 GB RAM; Python 3.13.18;
PostgreSQL 16.15; Redis 7; Node 22.23.4; Chrome for the browser suite.

| Check | Result |
|---|---|
| Backend suite, normal order, 5 consecutive runs (before the CORS tests) | 576 passed x 5 (79-82 s each) |
| Backend suite, random order, seeds 1111 / 2222 / 3333 (pytest-randomly, installed temporarily and removed) | 576 passed x 3 |
| Backend suite after adding the CORS tests | **579 passed** |
| Backend `ruff check`, `ruff format --check` | clean (173 files) |
| Mock services `ruff check`, `ruff format --check` | clean |
| Migrations: `alembic check` and downgrade to base / upgrade to head (in the suite) | pass |
| Frontend unit tests (`npm run test:ci`) | **60 passed** (17 files) |
| Frontend lint (ESLint + template accessibility rules), Prettier | clean |
| `npm run api:check`; snapshot equals the live OpenAPI document | match; match |
| Production build | success, initial 351.52 kB raw / 95.66 kB transfer |
| Browser suite (`npm run e2e`), 2 consecutive runs | **13 passed** x 2 (2.7 and 2.6 min) |
| Accessibility (axe, WCAG 2 A/AA, serious + critical), 14 pages x 2 themes | no violations (part of the browser suite) |

## 3. Windows results reported by the project owner

| Milestone | Result |
|---|---|
| 2 (`b0fb664`) | backend 547 passed, ruff clean; frontend 57 passed, lint clean, API types match |
| 3 (`b2af557`) | migration 0014; backend 555 passed; frontend 59 passed |
| 4 (`ec8cf49`) | migration 0015; backend 564 passed; frontend 60 passed |
| 5 (`7fa35a1`) | backend 576 passed; frontend 60 passed |
| 6 (`11aaa1c`) | migration 0016; backend 576 passed |

After every push the GitHub repository was compared file by file with the workspace copy:
identical each time.

## 4. Dependency and secret checks

| Check | Result |
|---|---|
| `pip-audit` 2.10.1: `backend/requirements.txt`, `backend/requirements-dev.txt`, `mock-services/requirements.txt` | No known vulnerabilities |
| `npm audit --omit=dev` (what ships to browsers) | 0 vulnerabilities |
| `npm audit` (including development tools) | 15 moderate, all one advisory: `minimatch` ReDoS (GHSA-g3hv-75wg-m249) inside the ESLint / angular-eslint / typescript-eslint toolchain. npm's proposed fix is a major-version *downgrade* of the linters. Accepted: development-time only, patterns come from our own config |
| Tracked files matching secret patterns (AWS, GitHub, Slack, private keys, Stripe, Google API keys; `password/secret/token = "..."`) | Only test values (`xoxp-1234567890-abcd` in an encryption test, `new-token-123` in a frontend unit test) |
| `.env` and `backend/.env` | ignored by git (`git check-ignore`) |

## 5. Security review

The full table is in [docs/15 section 11](15-security-design.md#11-phase-9-security-review-2026-11-13):
20 controls, each with its implementation and the tests that prove it.

**Finding:** CORS had no automated test. Three tests were added
(`test_cors_preflight_allows_the_configured_origin_and_needed_headers`,
`test_cors_ignores_other_origins`, `test_cors_exposes_the_headers_clients_read`); they pass.
No other gap was found between documented and tested controls.

## 6. Defects found during Phase 9 and fixed

| Where found | Defect | Fix |
|---|---|---|
| Milestone 3, live check | The new "Recent sign-ins" note suggested changing the password "through an administrator", a feature that does not exist | Reworded to "tell your administrator" |
| Milestone 4, live data | The "processing" duration looked too short: `started_at` is set on every pickup, so it measures the final attempt only | Described accurately as "final attempt" in the API schema, docs and UI (engine behaviour unchanged) |
| Milestone 5, test review | The OFFSET-versus-cursor test had one hire and one archive, which cancel out, so it proved nothing for v1 | Two hires and one archive (net shift); v1 repeats a row, v2 does not |
| Milestone 6, measurements | Employee pages were sorted after an index scan; the cursor page used a bitmap scan plus sort | Index widened to the full sort key (migration 0016); plain index scans, measured |
| Milestone 6, script | The throughput heading always said "one worker" | `--workers` option, recorded in the results |
| Milestone 7, review | CORS untested | Tests added (section 5) |

## 7. Acceptance criteria (from the plan)

| Criterion | Status | Evidence |
|---|---|---|
| Repeated failed logins or many logins from one IP get 429 with `Retry-After`; a later attempt works | Met | `test_security_hardening.py`; limiter window roll-over test |
| Common passwords and passwords with the email name refused | Met | parametrized weak-password test; CLI test; browser test |
| Oversized body gets 413 before the handler | Met | declared and streamed body tests |
| Sign-ins, failures, logouts and refusals recorded without secrets; table refuses UPDATE / DELETE | Met | `test_security_events.py` |
| A stopped worker or relay shows as stale within the timeout | Met | `test_system_status_reports_stale_components_and_stuck_events`; live: worker stopped 70 s -> "No worker has reported in the last 60 seconds" |
| Summary counts equal the list totals | Met | `test_summary_counts_equal_the_list_endpoints_totals` |
| v2 pages through all employees without duplicates or gaps under changes; v1 unchanged | Met | `test_api_v2.py` |
| Benchmarks run from one command, results recorded with the environment | Met | `benchmark.py`, `docs/performance/`, docs/19 |
| All test layers pass, including the migration round trip | Met | section 2 |
| No Phase 2-8 behaviour changed except as planned | Met | full suites unchanged and passing; the only behaviour changes are the listed controls |

## 8. Known limitations after Phase 9

- Browser session: bearer token in `sessionStorage`, no refresh token (30-minute
  sessions); an HttpOnly-cookie session would need backend and frontend changes.
- No MFA; no secrets manager for the connector encryption key; no OAuth
  authorization-code flow; all connectors are simulated.
- No retention jobs for events, attempts, audit and security events.
- Substring search and the summary read a whole organization (38-40 ms at 10,000
  employees on the test machine, docs/19 section 5).
- Throughput was measured on one 2-CPU machine with fast mocks; real SaaS latency and
  rate limits will dominate in practice.
- Fixed-window rate limits allow up to twice a limit across a boundary; the per-account
  limit can delay a known user's sign-in for one window (logged).
- Tests and the browser suite run locally; CI is Phase 10.

## 9. Next

Phase 10: Docker images and full-stack Compose, GitHub Actions CI, the deployment guide,
the remaining documents (01-04, 20, 22-24 with the ten case studies), a clean-machine run
of the README, and the final engineering report.
