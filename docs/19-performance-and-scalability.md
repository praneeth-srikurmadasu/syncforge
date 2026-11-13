# 19 - Performance and scalability

What was measured, how, on which machine, what changed because of it, and how SyncForge
scales beyond it. Every figure below comes from `infrastructure/scripts/benchmark.py`;
the raw results are in [`docs/performance/`](performance/). Nothing is estimated.

## 1. Environment

| | |
|---|---|
| Date | 2026-11-13 |
| Machine | Linux workspace (cloud VM), Intel Xeon @ 2.10 GHz, **2 logical CPUs**, 7.8 GB RAM |
| Software | Python 3.13.18, PostgreSQL 16.15, Redis 7, FastAPI under Uvicorn (1 process), Celery worker(s) with `--pool=solo`, the outbox relay, the three mock services |
| Topology | **Everything on the same 2-CPU machine**: database, broker, API, worker(s), relay, mocks and the load generator compete for the same CPUs |
| Data | A fresh organization per run (1,000 or 10,000 employees) in a database that also holds earlier test and demo data (about 3,100 employees and 3,100 events in total before the 10,000-employee run) |

These are **not production figures**. They show relative costs (which query is cheap,
what dominates a request, how processing scales with workers) on a stated, modest machine.
A production deployment has separate machines for the database and the application, more
CPUs, and network latency between them (docs/17).

## 2. Method

`benchmark.py` runs against the live stack, creating a new user and organization:

1. **Setup:** registers a user, creates five departments and N employees through the API
   (no workflow active, so their events complete without external calls).
2. **API latency:** for each endpoint, 20 warm-up requests, then R sequential requests;
   per-request time measured by the client (`perf_counter` around the HTTP call:
   includes JSON, auth, database, and loopback networking). Reported as nearest-rank
   p50 / p95 / p99 and mean. Sequential means one request at a time: latency, not maximum
   concurrency.
3. **Event throughput:** connects the three simulated connectors, activates a three-step
   onboarding workflow (Slack -> Google Workspace -> payroll, each a real HTTP call to the
   local mocks), sends H hires back to back, and waits until every event has completed.
   Throughput = H / (last completion - first hire). Per-event durations come from each
   event's own `created_at`, `started_at` and `completed_at`.
4. **Query plans:** `EXPLAIN (ANALYZE, BUFFERS)` of the SQL behind the busiest endpoints
   on the new organization, median execution time of 5 runs, the plan's node types, and
   rows touched by scan nodes. (The SQL is written to match what the repositories
   generate.)

Run it yourself (all processes started, from the repository root):

```powershell
& .\backend\.venv\Scripts\python.exe infrastructure\scripts\benchmark.py
# options: --employees 10000 --requests 100 --hires 100 --workers 2 --output results.json
```

## 3. Results

### 3.1 API latency (milliseconds, sequential, client-measured)

| Endpoint | 1,000 employees p50 / p95 | 10,000 employees p50 / p95 |
|---|---|---|
| `GET` v1 employees, page 1 (20 rows) | 13.6 / 17.1 | 12.2 / 15.3 |
| `GET` v1 employees, last page (OFFSET) | 12.0 / 14.8 | **27.6 / 35.4** |
| `GET` v2 employees, page 1 | 14.9 / 17.3 | 9.8 / 12.0 |
| `GET` v2 employees, last page (cursor) | 11.2 / 13.9 | **9.9 / 11.9** |
| `GET` v1 employees, search (substring) | 15.6 / 19.3 | **38.5 / 53.4** |
| `GET` employee detail | 9.1 / 11.5 | 8.1 / 9.7 |
| `GET` organization summary | 16.9 / 22.7 | **40.2 / 53.4** |
| `GET` events, page 1 | 9.5 / 11.4 | 9.1 / 11.4 |
| `POST` employee (create, with event and outbox row) | 15.4 / 22.6 | 11.8 / 17.1 |

1,000-employee column: after the index change in section 4 (`2026-11-13-after-index.json`,
200 requests each). 10,000-employee column: `2026-11-13-10k-employees.json`, 100 requests
each.

**Reading it:** at 1,000 employees every endpoint takes 9-17 ms, and the database part is
well under 1 ms for most of them (section 3.3). The rest is the per-request work in the
API (authentication and membership checks, session handling, serialization) on 2 shared
CPUs. At 10,000 employees three endpoints grow: the OFFSET last page, substring search,
and the summary. Each of them reads the whole organization. The cursor last page stays
as fast as page 1.

### 3.2 Event processing throughput (100 hires, 3 external calls each)

| Workers | Events / s | External calls / s | All done after | End to end p50 / p95 | Worker time per event p50 / p95 |
|---|---|---|---|---|---|
| 1 (1,000-employee run) | 9.5 | 28.5 | 10.8 s | 5.04 s / 8.74 s | 88 ms / 120 ms |
| 1 (10,000-employee run) | 10.2 | 30.6 | 10.2 s | 4.34 s / 8.14 s | 88 ms / 117 ms |
| 2 (`2026-11-13-two-workers.json`) | **16.3** | **48.7** | 6.3 s | 2.74 s / 4.47 s | 99 ms / 176 ms |

All 300 events of these runs completed (`statuses: ["completed"]`).

**Reading it:** a worker spends about 90 ms per event (three HTTP calls plus the
bookkeeping: claim, attempt rows, external-account links, audit entry). The 100 hires are
accepted in about 1.3 s, so they queue: end-to-end time is mostly waiting for a worker.
A second worker raised throughput 1.7x and halved the wait. It did not reach 2x because
the two workers share 2 CPUs with PostgreSQL, the API, the relay, the mocks and the load
generator. Each worker's own time per event rose slightly for the same reason.

### 3.3 Database (EXPLAIN ANALYZE, median of 5, milliseconds)

| Query | Before index change (1,000) | After (1,000) | After (10,000) | Plan after the change |
|---|---|---|---|---|
| Employee page 1, name order | 0.115 | **0.032** | 0.027 | Index Scan, no sort, 20 rows read |
| Employee last page by OFFSET | 1.739 | 2.519 | **16.162** | Seq Scan + Sort over the organization |
| Employee total (`count(*)`) | 0.256 | 0.464 | 1.838 | Seq Scan |
| Employee last page by cursor (v2) | 0.073 | **0.036** | **0.027** | Index Scan, no sort, 20 rows read |
| Substring search | 1.694 | 1.904 | 13.115 | Seq Scan (no index can serve `ILIKE '%x%'`) |
| Events page, newest first | 0.049 | 0.049 | 0.046 | Index Scan on (organization_id, created_at) |
| Summary: 24 h processing percentiles | 1.037 | 1.336 | 7.747 | Seq Scan + aggregate |

The 1,000-employee columns are separate runs on organizations of the same size; small
differences between them (0.1-1 ms) are noise on a shared machine. The trends are not
noise.

## 4. What changed because of the measurements

**Index on the full sort key (migration 0016).** Before: `(organization_id, last_name)`.
Because the list orders by `last_name, first_name, id`, PostgreSQL still sorted every page
(Incremental Sort on page 1, Bitmap Heap Scan + Sort for the cursor page; 66 and 85 rows
read for 20 returned). After: `(organization_id, last_name, first_name, id)`, which
replaces the old index. Page 1 and every cursor page are now plain Index Scans that stop
after 20 rows: page 1 went from 0.115 to 0.032 ms, the cursor page from 0.073 to 0.036 ms.
The cursor page stays at 0.027 ms with 10,000 employees.

OFFSET pages were not fixed and cannot be by an index: to return rows 9,981-10,000, the
database must produce and discard the 9,980 before them. This is the measured reason for
v2's keyset pagination (docs/08 section 14, ADR-0021). The API difference at 10,000
employees: 27.6 ms (OFFSET) against 9.9 ms (cursor).

## 5. Known hot spots and what would address them

| Hot spot (at 10,000 employees) | Cause | Options, in order of effort |
|---|---|---|
| Substring search 38.5 ms (DB 13.1 ms) | `ILIKE '%term%'` over name, email, number cannot use a B-tree index | `pg_trgm` GIN index on those expressions; or prefix search with a B-tree on `lower(...)`; or a search engine for large tenants |
| Summary 40.2 ms | Counts by status and 24 h percentiles scan the organization's employees and events | Partial index on `integration_events (organization_id, completed_at) WHERE status = 'completed'`; cache the summary for a few seconds; maintained counters |
| OFFSET last page 27.6 ms | OFFSET reads skipped rows | Use v2 for walking the directory; the UI's page numbers are fine for the first pages people actually open |
| Event processing about 10 events/s per worker | About 90 ms of worker time per event (three external calls in sequence) | More workers (section 6); parallel steps within a workflow (docs/11 section 6, future); for real SaaS APIs the external call latency will dominate and differ per application |

None of these was changed in Phase 9. At the measured sizes they are within tens of
milliseconds, and each option has a cost (a PostgreSQL extension, cache invalidation,
write overhead) that should be justified by a real tenant's size.

## 6. How SyncForge scales

| Part | Scales by | Limits and coordination |
|---|---|---|
| API | More Uvicorn processes / instances behind a load balancer; stateless (JWT, no session state) | Shared PostgreSQL connections: each process has a SQLAlchemy pool (`pool_size=5` today, `app/core/database.py`); processes x pool must stay under PostgreSQL's `max_connections`, so many instances need a pooler (PgBouncer) |
| Workers | More worker processes or machines (`--pool=solo` per process on Windows; prefork with concurrency on Linux). Measured: 2 workers -> 1.7x on 2 CPUs | Events are claimed atomically with leases (docs/09), so any number of workers can run; per-employee ordering across workers is not guaranteed (steps read current state, docs/09 section 8); connector rate limits and circuit breakers are shared in PostgreSQL, so more workers do not exceed an application's limits |
| Outbox relay | One process is enough at these rates (it publishes in batches); a second is safe (rows are claimed with `FOR UPDATE SKIP LOCKED`) | |
| PostgreSQL | Vertical first; read replicas for reporting; every query is scoped by `organization_id`, so partitioning or sharding by organization is the long-term path | Retention jobs for events, attempts, audit and security events (not implemented yet) would keep tables small |
| Redis | A broker only (no state SyncForge depends on); a managed Redis is enough | If Redis is lost, events wait in the outbox and are re-published |

## 7. Limitations of these measurements

- One shared 2-CPU machine. Absolute numbers would be lower on separate, larger machines,
  and network latency between them would add to each database round trip.
- Latency is sequential (one request at a time). The maximum request rate under concurrent
  load (and where it saturates) was not measured.
- The mock services answer in a few milliseconds; real Slack and Google APIs take tens to
  hundreds of milliseconds and enforce their own rate limits, which would lower events per
  second per worker.
- Database sizes are small (up to about 13,000 employees in total). Plans can change at
  millions of rows; run the benchmark with `--employees` at the target size before
  relying on these conclusions.
- Windows results were not collected; the script runs there too (memory size is reported
  only on Linux).
