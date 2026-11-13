# 18 - Observability

How to tell whether SyncForge is healthy, how long synchronization takes, and how to
follow one change from the API request to every external call. Everything here is
implemented; future options are marked as such in section 7.

## 1. Signals at a glance

| Question | Where to look |
|---|---|
| Is the API process up? | `GET /health` (never touches dependencies) |
| Can the API serve traffic? | `GET /ready` (checks PostgreSQL; `503 not_ready` otherwise) |
| Are workers and the relay alive? Is there a backlog? | `GET /api/v1/system/status` (Super Admins) |
| How is one organization doing, how fast is processing? | `GET /api/v1/organizations/{id}/summary`, shown on the dashboard |
| What happened to one employee change? | `GET .../events/{id}` and `.../attempts`; logs by request / correlation ID |
| Who did what? | Audit log (`GET .../audit-logs`), sign-ins in `security_events` |
| How long did a request or a delivery take? | `request completed` and `event delivery finished` log lines (`duration_ms`) |

## 2. Structured logs and IDs

Every process (API, worker, relay) writes one JSON object per line
(`app/core/logging.py`): `timestamp`, `level`, `logger`, `message`, `request_id`, plus
fields of the message. Personal values, passwords, tokens and credentials are never
logged (docs/15 section 6).

| ID | Created by | Appears in |
|---|---|---|
| `request_id` | API middleware (or the caller's `X-Request-ID` if it is a safe string) | Every API log line, the `X-Request-ID` response header, every error body, audit and security events |
| `correlation_id` | The API request that changed the employee | The event (`GET .../events/{id}`); a worker uses it as its `request_id`, so worker lines link back to the request |
| `event_id` | The outbox write | Event APIs, dead letters, `event processing started`, `event delivery finished` |
| `connector_id`, `job_id` | Configuration, the engine | Connector and job log lines, attempt history |

Messages worth knowing:

| Logger | Message | Fields |
|---|---|---|
| `syncforge.request` | `request completed` | `method`, `path`, `status_code`, `duration_ms` |
| `syncforge.worker` | `event delivery finished` (Phase 9) | `event_id`, `outcome` (`completed`, `retrying`, `dead_letter`, `skipped`, `error`), `duration_ms` |
| `syncforge.engine` | `event processing started` / `finished`, `synchronization job finished`, `synchronization job deferred by rate limit` | event, job, connector, outcome, category |
| `syncforge.relay` | `outbox rows published`, `retry dispatched`, `event re-dispatched after lease expiry`, `outbox publish failed` | counts, event IDs |
| `syncforge.auth` | `login succeeded`, `login failed` (`reason`), `rate limited` (`rule`) | user ID when known |
| `syncforge.heartbeat` | `heartbeat failed` | `component` |

## 3. Health of background processing

### Heartbeats

Workers and the outbox relay record that they are alive in `component_heartbeats`
(migration 0015), one row per process (`host:pid`):

- **Worker:** a daemon thread started on Celery's `worker_ready` signal upserts the row
  every `HEARTBEAT_INTERVAL_SECONDS` (default 15). It runs beside task execution, so a
  long task does not make the worker look dead.
- **Relay:** its polling loop beats at most once per interval.
- A failed heartbeat is logged and never stops the process. Rows not seen for a day are
  deleted by later heartbeats.

### `GET /api/v1/system/status` (Super Admins)

Computed from PostgreSQL only:

| Field | Meaning |
|---|---|
| `components.worker[]`, `components.relay[]` | Each process with `started_at`, `last_seen_at`, `seconds_since_seen`, `healthy` (seen within `HEARTBEAT_STALE_AFTER_SECONDS`, default 60) |
| `outbox_unpublished`, `outbox_oldest_unpublished_seconds` | Events written but not yet handed to Redis. Growing: the relay is down or Redis is unreachable |
| `events_by_status`, `events_oldest_pending_seconds` | Platform-wide event states. An old pending event: no worker is consuming |
| `events_stuck_processing` | Events still `processing` after their lease ran out: a worker died mid-event (the relay re-dispatches them) |
| `dead_letters_open` | Work waiting for a person |
| `healthy`, `problems[]` | False with a reason when no worker or no relay is healthy, or events are stuck |

Verified in the workspace (2026-11-12): with the worker stopped for 70 seconds the
endpoint returned `healthy: false` and "No worker has reported in the last 60 seconds."
A newly started worker appeared as a new healthy instance within 20 seconds.

### Why `/ready` does not include workers

Readiness answers "can this API process take requests?". If it failed whenever a worker
was down, a load balancer would take every API instance out of service, and users could
not even record the changes that will be processed once the worker returns. Employee
changes are durable in the outbox either way. So: `/ready` is database-only, and
background health is a separate signal for operators and alerting.

## 4. Organization summary and processing durations

`GET /api/v1/organizations/{id}/summary` (`org:read`, any member) returns in one request:

- employees by status (archived excluded), workflows active / total, connectors by status,
  events by status, open dead letters, open conflicts by severity - each equal to the
  `total` of the matching list request (`test_summary_counts_equal_the_list_endpoints_totals`);
- `processing` over the last 24 hours, for completed events:
  - `end_to_end_seconds` - employee change recorded to completion (p50, p95, max);
  - `processing_seconds` - the final attempt: last worker pickup to completion. The engine
    sets `started_at` on every pickup, so this is the worker time of the attempt that
    succeeded. The gap between the two is queueing, retry waits, and waits for rate
    limits or open circuits.

Percentiles are PostgreSQL `percentile_cont` (linear interpolation) over event
timestamps; they are exact for the window, not sampled.

The dashboard uses this endpoint instead of one `limit=1` list call per figure. Measured
in the workspace on the same organization: **48 API requests per dashboard load before,
33 after**. The remaining requests are mostly the 7-day audit-log windows (21 calls, which
need `audit:read` and so stay separate), the recent-activity list, and one name lookup per
distinct employee in the recent-events table.

## 5. Investigating a failed synchronization

1. **Is anything running?** `GET /api/v1/system/status`: stale worker or relay, outbox
   backlog, stuck events.
2. **Which event?** Dashboard, `GET .../events?event_status=retrying` (still trying) or
   `GET .../dead-letter-events?entry_status=open` (gave up).
3. **Which step and why?** `GET .../events/{event_id}`: executions, jobs, each job's
   `error_category` and `next_attempt_at`. `GET .../events/{event_id}/attempts`: every
   external call with HTTP status, retryable or not, duration and the scheduled retry.
4. **The logs:** search for the event's `correlation_id` (the `request_id` of the API call
   that caused it) to see the API request, the `employee lifecycle event`, and every
   worker line; or search for the `event_id`.
5. **Fix and replay:** correct the cause (credentials, permissions, the application's
   outage), then replay the dead-letter entry. Symptom tables: [docs/21](21-troubleshooting.md).

## 6. Configuration

| Setting | Default | Meaning |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Log level for API, worker, relay |
| `HEARTBEAT_INTERVAL_SECONDS` | 15 | How often workers and the relay record a heartbeat |
| `HEARTBEAT_STALE_AFTER_SECONDS` | 60 | After this, a process is reported as not healthy |

## 7. Not implemented (options for later)

- A Prometheus `/metrics` exporter, OpenTelemetry traces. The JSON endpoints above carry
  the same figures without a new dependency; an exporter is a natural addition once a
  metrics stack exists (alert suggestions: docs/17 section 9).
- Alerting. `system/status` is designed to be polled by an external monitor; SyncForge
  does not send alerts itself.
- Per-connector latency percentiles over time; attempt durations are stored per call and
  shown per event today.
