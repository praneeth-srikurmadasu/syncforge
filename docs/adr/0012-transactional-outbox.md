# ADR-0012: Transactional outbox for publishing events

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
Every employee change produces lifecycle events (Phase 3) that must reach the background
workers through Redis ([ADR-0010](0010-redis-and-celery-for-background-work.md)). The
employee is stored in PostgreSQL. PostgreSQL and Redis cannot take part in one transaction.

## Problem
How to make sure that an event is published **if and only if** the employee change was
committed - without a distributed transaction.

The naive orders both fail:
- *commit, then publish:* a crash or a Redis outage between the two loses the event; the
  employee is hired and no accounts are ever created, silently;
- *publish, then commit:* workers may act on a change that then rolls back.

## Considered alternatives
| Option | Assessment |
|---|---|
| Publish after commit, best effort | Simple; loses events on crashes and broker outages, with no trace. |
| Two-phase commit (XA) across database and broker | Redis does not support it; heavy and fragile even where available. |
| Change data capture (e.g. Debezium reading the PostgreSQL WAL) | Robust and decoupled; adds Kafka Connect-style infrastructure far beyond this project's size. |
| **Transactional outbox + relay** | Events become rows written in the same transaction as the change; a separate relay publishes them. Standard, simple, testable. |

## Decision
- `EmployeeService` calls `record_events()` **before** committing. In the same transaction it
  writes the employee row, one `integration_events` row per lifecycle event (status
  `pending`, payload, correlation ID = request ID) and one `outbox_events` row per event.
- The **outbox relay** (`python -m app.cli outbox-relay`) polls unpublished rows oldest first
  with `FOR UPDATE SKIP LOCKED`, publishes each event ID to Redis, and marks the row
  published. A failed publish is recorded on the row and retried on the next poll.
- The relay also re-dispatches events whose lease expired (crashed worker, lost message),
  resetting abandoned `processing` events to `pending`.
- The lifecycle log line is written only after the commit and includes the event ID.

## Trade-offs
- Publication latency: up to one poll interval (default 1 s) after the commit.
- A relay crash between publishing and marking published causes a duplicate publish. This is
  accepted and harmless because consumers are idempotent
  ([ADR-0011](0011-asynchronous-event-processing.md)).
- Outbox and event tables grow; a retention job that removes old published rows is a future
  improvement (nothing is deleted today).
- Polling adds a small constant query load (one indexed query per second per relay, on a
  partial index of unpublished rows).

## Consequences
- An employee change and its events are atomic: `test_employee_change_and_its_events_share_one_transaction`
  makes the outbox write fail and proves the employee was not saved either.
- Events recorded while no worker or relay is running are processed when they start - seen
  in the Windows live run, where three waiting events were published (`count: 3`) and
  processed in order as soon as the relay and worker came up.
- Several relays can run for availability; `SKIP LOCKED` keeps them from publishing the same
  row in parallel.
