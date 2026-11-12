# ADR-0016: Circuit breaker and rate limits per connector, with state shared in PostgreSQL

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
Retries help one job; during an outage they multiply load on the failing application and
keep workers waiting on timeouts. Separately, SaaS APIs publish rate limits that a burst of
hires can exceed. Several Celery workers (and processes) call the same connectors.

## Problem
How to stop calling an application that is down, and pace calls under a known limit,
consistently across all workers.

## Considered alternatives
| Option | Assessment |
|---|---|
| In-process breaker / limiter per worker (e.g. `pybreaker`) | Each worker learns about an outage separately; N workers allow N times the limit. |
| Redis-based breaker and token bucket | Shared and fast; but Redis runs without persistence here, and keeping the state next to the jobs it governs makes it visible and testable in the same transactions. |
| A service mesh / API gateway in front of the vendors | Infrastructure this project does not have. |
| **Rows in PostgreSQL: `connector_circuits` (breaker) and `connector_rate_windows` (fixed one-minute windows), locked for milliseconds per call** | Shared by every worker, durable, inspectable through the API, no new component. Throughput is far above what provisioning traffic needs. |

## Decision
- **Breaker per connector**: closed -> open after `CIRCUIT_FAILURE_THRESHOLD` (5)
  consecutive outage failures (`server`, `timeout`, `network`); any real answer (including
  4xx and 429) resets the count. Open refuses calls with retryable `circuit_open` and
  `retry_after` until `open_until` (`CIRCUIT_OPEN_SECONDS`, 60). Then one trial call
  (half-open): success closes, failure re-opens; an abandoned trial is replaced. A
  successful manual connection test closes it. A refusal counts as an attempt, so waiting
  is bounded by the retry budget. State is exposed on connector responses.
- **Rate limit per connector**: optional `rate_limit_per_minute` in the connector config;
  an atomic `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` counts calls per minute; a job
  over the limit is deferred to the next window without using an attempt.
- **Operation deadline**: `CONNECTOR_OPERATION_TIMEOUT_SECONDS` (30) caps one operation
  across all of its requests, in addition to per-request connect/read timeouts.

## Trade-offs
- Every external call adds two short database round trips (breaker check and record), plus
  one for connectors with a rate limit.
- A fixed window allows up to twice the limit across a window boundary.
- Counting refusals as attempts means a long outage dead-letters work (recoverable by one
  replay) rather than waiting indefinitely.
- Hot rows: one connector's breaker row is updated on every call to it. Acceptable at
  provisioning volumes; at much higher volumes the state would move to Redis.

## Consequences
- In the demonstration run (docs/12, section 10), three hires during a Google outage
  produced 5 failing requests before the breaker opened and none while it was open; after
  the open period one trial call closed it and all three completed, with exactly three
  Google accounts.
- `test_an_open_circuit_stops_calls_from_every_job` and
  `test_jobs_over_the_limit_wait_without_using_an_attempt` cover the engine integration.
