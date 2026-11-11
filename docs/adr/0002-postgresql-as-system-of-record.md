# ADR-0002: PostgreSQL as the system of record

- **Status:** Accepted
- **Date:** 2026-11-11

## Context
SyncForge stores tenants, users, employees and — in later phases — events, synchronization
attempts and audit logs. Correctness under concurrency (no duplicate users, no lost events)
matters more than raw write throughput.

## Problem
Choose the primary datastore.

## Considered alternatives
| Option | Assessment |
|---|---|
| **PostgreSQL** | ACID transactions, rich constraints (unique, check, foreign keys), `ON CONFLICT`, row locking (`SELECT … FOR UPDATE SKIP LOCKED` for the outbox relay), JSONB for event payloads. |
| MySQL | Capable, but weaker CHECK-constraint history and fewer features used here. |
| MongoDB | Flexible documents, but relational integrity (memberships, foreign keys) would move into application code. |
| SQLite | Great for tests, but no concurrent writers and different SQL dialect from production. |

## Decision
Use **PostgreSQL 16** for all persistent state, run locally via Docker Compose. Tests run
against a real PostgreSQL database, not SQLite, so they exercise the same constraints and SQL.

## Trade-offs
- Requires Docker (or a local server) for development and tests.
- Some queries use PostgreSQL-specific features (`ON CONFLICT DO NOTHING`), tying the code
  to PostgreSQL.

## Consequences
- Data rules are enforced by the database itself (e.g. lowercase unique emails, valid roles,
  cascade deletes) and are covered by tests in `tests/test_models.py`.
- The same database will host the transactional outbox (Phase 5), giving atomic
  "save data + record event" writes without a distributed transaction.
