# ADR-0010: Redis and Celery for background work

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
From Phase 5, employee events are processed outside the API request by background workers
([ADR-0011](0011-asynchronous-event-processing.md)). Workers need a way to receive "process
event X" messages, scale horizontally, and survive restarts. The project brief names Redis
and Celery (or a justified alternative). The team is small, the stack is Python, and the
system must run on a developer's Windows machine with Docker Desktop.

## Problem
Which message broker and worker framework to use, given that correctness must not depend on
the broker (the database is the source of truth, [ADR-0012](0012-transactional-outbox.md)).

## Considered alternatives
| Option | Assessment |
|---|---|
| **Celery + Redis** | Mature, widely known, late acknowledgement and redelivery built in; Redis is one small container. Celery's default process pool does not run on Windows (solo pool needed locally). |
| RQ (Redis Queue) | Simpler API, but fewer delivery controls (no late-ack semantics comparable to Celery's) and no native Windows worker. |
| Dramatiq + Redis/RabbitMQ | Clean design and good defaults; smaller ecosystem and less familiar to reviewers and interviewers. |
| RabbitMQ (with Celery) | Stronger delivery guarantees and routing than Redis; one more heavyweight service to run and operate for little gain here, because state lives in PostgreSQL anyway. |
| Kafka | Log-based streaming with replay; far beyond what this workload needs, and much heavier to operate locally. |
| PostgreSQL as the queue (polling with `SKIP LOCKED`, no broker) | Fewest moving parts; the outbox relay already polls. But it puts all worker polling load on the database and does not demonstrate a message broker, which the brief asks for. |

## Decision
- **Redis 7** (Docker Compose service `redis`) as the broker, **without persistence**
  (`--save "" --appendonly no`): it only carries event IDs, and anything it loses is re-sent
  by the outbox relay.
- **Celery 5.7** workers (`app/workers/celery_app.py`), JSON serialization only, results
  ignored (state is in PostgreSQL), `task_acks_late`, `task_reject_on_worker_lost`,
  `worker_prefetch_multiplier=1`, visibility timeout twice the worker lease.
- One queue (`syncforge-events`) and one task (`syncforge.process_event`) for now.
- On Windows, workers run with `--pool=solo`, started as `python -m celery` from the project
  virtual environment.

## Trade-offs
- Redis is not a durable broker in this configuration; a Redis restart loses queued
  messages. Accepted, because the outbox relay's recovery step re-sends them after one lease
  period. The cost is latency, not lost work.
- Celery adds a sizeable dependency for one task today; it pays off as Phase 6 adds
  scheduled retries and more task types.
- `--pool=solo` means one task at a time per worker process on Windows; scaling is done with
  more processes (production on Linux uses the prefork pool with `--concurrency`).

## Consequences
- Local development runs four processes besides the containers: API, worker, relay, mocks.
- Tests do not need Redis: `test_celery_worker.py` runs a real Celery worker with the
  in-memory broker in a thread.
- Swapping the broker (for example to RabbitMQ) is a configuration change (`REDIS_URL` ->
  broker URL) plus deployment, with no change to the engine or the outbox.
