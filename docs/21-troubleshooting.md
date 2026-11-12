# 21 - Troubleshooting

> **Scope:** problems actually met while building and running SyncForge (Phases 1-7), with
> their causes and fixes. Later phases add their own entries.

## Investigating a failed request

Every response has an `X-Request-ID` header and every error body has `error.request_id`.
Search the API log for that ID: every line written while handling the request carries it,
including connector calls (`syncforge.connectors`) and the outbound HTTP request (`httpx2`).

## Investigating a failed synchronization

1. `GET .../dead-letter-events?entry_status=open` lists work that failed for good, with the
   preserved error (connector, operation, category, HTTP status, message, attempts, reason).
   `GET .../events?event_status=retrying` lists work that is still being retried.
2. `GET .../events/{event_id}` shows each workflow execution and job: which step failed,
   its `error_category`, `error_message` and `next_attempt_at`.
   `GET .../events/{event_id}/attempts` lists every external call: timing, outcome, HTTP
   status, whether it was retryable, and when the next attempt was scheduled.
3. Search the worker log for the event's `correlation_id` (the request ID of the API call
   that caused it) or its `event_id`: `event processing started`, one
   `synchronization job finished` per attempt, `event dead-lettered`,
   `event processing finished`. `circuit opened` / `circuit closed` lines carry the
   connector ID.
4. Fix the cause (credentials, permissions, the application's outage), then replay the
   entry (`POST .../dead-letter-events/{id}/replay`, Integration Manager or Org Admin).

## Events and workers

| Symptom | Cause | Fix |
|---|---|---|
| Events stay `pending`; nothing happens after creating an employee | The outbox relay or the worker is not running (or Redis is down) | Start Redis (`docker compose up -d redis`), the worker and the relay (docs/09, section 10). Nothing is lost: waiting events are published and processed in order once they run |
| Relay logs `outbox publish failed` with `Connection refused` | Redis is not running | `docker compose up -d redis`; the relay retries on its next poll |
| The worker terminal shows a traceback from **another project's** folder (e.g. `...\other-project\venv\Scripts\celery.exe`) using a different Python | The SyncForge virtual environment is not active, and another project's `Scripts` folder is on `PATH`, so a bare `celery` command runs that project's Celery | Start it with the project's interpreter: `& "$HOME\Projects\syncforge\backend\.venv\Scripts\python.exe" -m celery -A app.workers.celery_app worker --loglevel=INFO --pool=solo` |
| `ModuleNotFoundError: No module named 'sqlalchemy'` (relay) or `'mockservices'` (mocks) | Started with the system Python, or from the wrong folder | Use absolute folders and the venv's `python.exe` as in docs/09, section 10 |
| `Set-Location : Cannot find path '...\backend\mock-services'` | The terminal was already inside `backend`, so a relative path pointed to the wrong place | Use `Set-Location "$HOME\Projects\syncforge\mock-services"` |
| Worker fails to start on Windows with a pool error | Celery's default (prefork) pool is not supported on Windows | Add `--pool=solo`; scale with more worker processes |
| An event stays `processing` after a worker was killed | Expected until its lease expires (`WORKER_LEASE_SECONDS`, default 300 s) | Wait: the relay logs `event re-dispatched after lease expiry` and the next worker resumes it. For demos, set `$env:WORKER_LEASE_SECONDS = "20"` in the worker and relay terminals |
| A hire's `create_user` steps are all `skipped` | The employee was terminated before the worker processed the hire; workers act on current state | Expected and safe: no access is created for terminated employees (docs/09, section 8) |
| `deactivate_user` steps are `skipped` | The employee never had an account in that application | Expected |
| A step `failed` with category `configuration` | The connector is disconnected, or its stored version is no longer supported | Reconnect it (`PATCH .../connectors/{id}` with credentials), then replay the dead-letter entry |
| A workflow cannot be activated (`409 connector_disconnected`) | One of its steps uses a disconnected connector | Reconnect the connector or change the step |

## Retries, dead-letter queue, circuit breaker

| Symptom | Cause | Fix |
|---|---|---|
| An event stays `retrying` for a while | A step failed with a retryable error and waits for `next_attempt_at` (2, 4, 8, 16 s by default; longer with `Retry-After` or an open circuit) | Expected. `GET .../events/{id}/attempts` shows each attempt. The relay must be running: it dispatches due retries |
| Steps fail with `circuit_open` and no HTTP status | That connector's circuit breaker is open after repeated outage failures; no request is sent | Wait for the open period (`CIRCUIT_OPEN_SECONDS`, 60 s) - one trial call then decides - or, once the application is back, run a connection test: success closes the breaker. `GET .../connectors/{id}` shows `circuit` |
| A job shows `error_category: throttled` and attempts `0` | The connector's `rate_limit_per_minute` is reached; the job waits for the next minute without using an attempt | Expected; raise or remove the limit in the connector config if it is too low |
| `409 already_replayed` | The entry was replayed already (by you or someone else) | Follow the event; if it failed again, a new open entry exists |
| `409 workflow_inactive` on replay | None of the workflows that failed is active | Fix the configuration, activate the workflow, replay again |
| A step fails with `in_progress` (409 `idempotency_key_in_use`) | An earlier attempt with the same idempotency key is still running at the application (it timed out on our side) | Expected and retryable: a later attempt receives the original result |
| The demo script times out waiting for events | The worker or the relay is not running, or a mock fault is still queued | Start them (docs/09, section 10); `DELETE http://127.0.0.1:910x/_mock/faults` |

## Audit log, concurrent edits, data conflicts

| Symptom | Cause | Fix |
|---|---|---|
| `412 version_conflict` when saving an employee | Someone changed the employee after you loaded it (`details` shows both versions) | Reload, re-apply your change, save with the new `ETag` in `If-Match` |
| `422 invalid_if_match` | `If-Match` is not an ETag from this API | Send the `ETag` header value exactly, e.g. `"3"` |
| `403` on `GET .../audit-logs` | Viewers do not have `audit:read` | Ask an Organization Admin or Integration Manager |
| `audit_logs is append-only (UPDATE refused)` / `(DELETE refused)` from SQL or a migration | The table is append-only by design (trigger) | Do not change history. A retention job must run `SET LOCAL syncforge.allow_audit_delete = 'on'` in its own transaction |
| Who did it? | | `GET .../audit-logs?resource_type=employee&resource_id=<id>`; `request_id` in an entry finds the matching API and worker log lines |
| `422 resolution_against_policy` | The policy names the other side as authoritative for this field | Use the authoritative side, or send `override: true` with a note; or change the policy (Org Admin) |
| `409 conflict_stale` | The employee changed after the conflict was detected | Run `POST .../connectors/{id}/reconcile` again and decide on the refreshed conflict |
| `422 department_not_found` when adopting a department | SyncForge has no department with that name | Create the department first, or keep SyncForge's value |
| `422 reactivation_not_supported` | Connectors cannot re-enable accounts | Reactivate the account in the application, or adopt its state (`use_external`) |
| Reconcile reports `errors` with `not_found` | The account was deleted in the application | Re-provision (create the account again) or unlink; investigate who deleted it there |
| Reconcile stops early with `circuit_open` | The application is failing; its circuit breaker is open | Wait for the open period or run a connection test once it is back, then reconcile again |

## API calls from PowerShell

| Symptom | Cause | Fix |
|---|---|---|
| `{"error":{"code":"token_expired",...}}` after a while | Access tokens are valid for 30 minutes (setting `ACCESS_TOKEN_EXPIRE_MINUTES`) | Log in again and rebuild the `Authorization` header |

## Connectors

| Symptom | Cause | Fix |
|---|---|---|
| Creating a connector returns `503 encryption_not_configured` | `CONNECTOR_ENCRYPTION_KEY` is missing or blank in `.env` | Generate a key (README, Quick start) and restart the API |
| Connection test returns `ok: false`, `error.category: "network"` or `"timeout"` with `connect_timeout` | The mock service (or the real API) is not running, or is on another port | Start the mock (`mock-services/README.md`); check the connector's base URL |
| Connection test or operation fails with `category: "server"` although the mock is running | A fault queued earlier is still waiting (faults survive until used) | `GET http://127.0.0.1:9101/_mock/state` shows queued faults; `DELETE .../_mock/faults` clears them |
| `category: "authentication"` | Wrong credentials for that connector | Rotate them with `PATCH .../connectors/{id}` and test again |
| `422 host_not_allowed` when saving a base URL | The host is not in `CONNECTOR_ALLOWED_HOSTS` (SSRF protection) | Add the host to the allowlist only if it is a trusted vendor endpoint |
| Every connector call takes about 2 seconds on Windows | The base URL uses `localhost`, which Windows tries over IPv6 first | Use `127.0.0.1` (the default since Phase 4); fix any `*_BASE_URL=http://localhost:...` lines in `.env` |

## Tests

| Symptom | Cause | Fix |
|---|---|---|
| Every test errors at setup | PostgreSQL is not running | `docker compose up -d postgres` |
| Tests need Redis? | No - `test_celery_worker.py` uses Celery's in-memory broker | - |
| Windows asks whether Python may use the network during tests | The connector tests start the mocks as local HTTP servers on `127.0.0.1` | Allow on private networks only |
| A refused-connection test reports `timeout` instead of `network` on Windows | Windows retries refused loopback connections for ~2 s | Already handled: that test uses a 5 s connect timeout (docs/10, section 13) |

## Git and the terminal (Windows)

| Symptom | Cause | Fix |
|---|---|---|
| `git log` output ends with `:` and waits | Git opened its pager | Press `q`; use `git --no-pager log ...` or `git config core.pager ""` |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | PowerShell execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`, then activate again |
