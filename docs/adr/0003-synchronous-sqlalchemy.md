# ADR-0003: Synchronous SQLAlchemy 2.x with Alembic migrations

- **Status:** Accepted
- **Date:** 2026-11-11

## Context
FastAPI supports both `async` and regular (sync) endpoints. The database layer will be shared
by the API and by Celery workers (Phase 5), which are synchronous.

## Problem
Choose the ORM style and how the schema is created and evolved.

## Considered alternatives
| Option | Assessment |
|---|---|
| Async SQLAlchemy (`asyncpg`) | Higher concurrency per process for I/O-bound endpoints, but every caller must be async; Celery workers would need a second, sync code path. |
| **Sync SQLAlchemy 2.x (`psycopg` 3)** | FastAPI runs sync endpoints in a thread pool; one data-access code path serves both API and workers. |
| `Base.metadata.create_all()` at startup | Simple, but cannot evolve an existing schema and hides changes from review. |
| **Alembic migrations** | Versioned, reviewable, reversible schema changes. |

## Decision
Use **synchronous SQLAlchemy 2.x** with the `psycopg` 3 driver, and **Alembic** for every
schema change. The application never creates tables at startup.

## Trade-offs
- Each in-flight request holds a thread-pool thread while waiting on the database; very
  high concurrency would need more API processes rather than more coroutines.

## Consequences
- Repositories and services are reused unchanged by background workers.
- The test suite rebuilds the schema from migrations and runs `alembic check`, so the
  models and migrations cannot silently drift apart.
