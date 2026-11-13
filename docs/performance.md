# Performance

Every figure here comes from `infrastructure/scripts/benchmark.py`, and the raw results
are in [`docs/performance/`](performance/). These are **not production figures**. They
show relative costs on a small, stated machine.

| | |
|---|---|
| Date | 2026-11-13 |
| Machine | Linux cloud VM, Intel Xeon 2.1 GHz, **2 logical CPUs**, 7.8 GB RAM |
| Topology | Everything on the same machine: PostgreSQL 16, Redis 7, API (1 Uvicorn process), worker(s), relay, mocks and the load generator |
| Method | A fresh organization per run. Latency: 20 warm-up requests, then sequential requests timed by the client. Throughput: a three-step onboarding workflow over real HTTP to the mocks. Queries: `EXPLAIN ANALYZE`, median of 5 runs. |

Run it yourself (with the stack running):
```bash
python infrastructure/scripts/benchmark.py --employees 10000 --requests 100 --hires 100 --workers 2
```

## 1. API latency (ms, p50 / p95)

| Endpoint | 1,000 employees | 10,000 employees |
|---|---|---|
| Employee list, page 1 | 13.6 / 17.1 | 12.2 / 15.3 |
| Employee list, last page, v1 (OFFSET) | 12.0 / 14.8 | **27.6 / 35.4** |
| Employee list, last page, v2 (cursor) | 11.2 / 13.9 | **9.9 / 11.9** |
| Employee search (substring) | 15.6 / 19.3 | 38.5 / 53.4 |
| Employee detail | 9.1 / 11.5 | 8.1 / 9.7 |
| Organization summary | 16.9 / 22.7 | 40.2 / 53.4 |
| Create employee (with event and outbox row) | 15.4 / 22.6 | 11.8 / 17.1 |

At 1,000 employees every endpoint takes 9-17 ms, and the database part is well under
1 ms for most of them. The rest is per-request work (authentication, membership check,
serialization) on 2 shared CPUs. At 10,000 employees, three endpoints grow because each
reads the whole organization: the OFFSET last page, substring search and the summary. The
cursor page stays as fast as page 1.

## 2. Event processing (100 hires, 3 external calls each)

| Workers | Events/s | External calls/s | End to end p50 / p95 | Worker time per event p50 |
|---|---|---|---|---|
| 1 | 9.5-10.2 | 28.5-30.6 | 4.3-5.0 s / 8.1-8.7 s | 88 ms |
| 2 | **16.3** | **48.7** | 2.7 s / 4.5 s | 99 ms |

All 300 events completed. A worker spends about 90 ms per event: three HTTP calls plus
the claim, the attempt rows and the audit entry. The 100 hires are accepted in about
1.3 s and then queue, so end-to-end time is mostly waiting for a worker. A second worker
raised throughput 1.7×. It did not reach 2× because both workers share 2 CPUs with
everything else.

## 3. What the measurements changed

**Migration 0016.** The employee index was widened from `(organization_id, last_name)`
to the full sort key `(organization_id, last_name, first_name, id)`. Page 1 and every
cursor page became plain index scans that stop after 20 rows:
- page 1 went from 0.115 ms to 0.032 ms;
- the cursor page went from 0.073 ms to 0.036 ms, and stays at 0.027 ms with 10,000
  employees.

An OFFSET page cannot be fixed by an index. To return rows 9,981-10,000, the database
must produce and discard the 9,980 before them (16 ms of database time at 10,000
employees). That is the measured reason for the v2 cursor pagination
([ADR-0021](adr/0021-path-versioning-and-keyset-pagination.md)).

## 4. Known hot spots

| Hot spot (10,000 employees) | Options |
|---|---|
| Substring search, 38.5 ms | A `pg_trgm` GIN index, or prefix search on `lower(...)` |
| Summary, 40.2 ms | A partial index on completed events, or a short cache |
| About 10 events/s per worker | More workers; parallel workflow steps |

None of these was changed. They cost tens of milliseconds at the measured sizes, and
each option has a cost of its own that a real tenant's size should justify.

## 5. Limitations

- One shared 2-CPU machine. Separate, larger machines would change the absolute numbers,
  and network latency between them would add to each database round trip.
- The latencies are sequential. The request rate under concurrent load was not measured.
- The mocks answer in milliseconds. Real SaaS APIs take tens to hundreds of milliseconds
  and enforce their own limits.
- Up to about 13,000 employees in total. Query plans can change at millions of rows.
