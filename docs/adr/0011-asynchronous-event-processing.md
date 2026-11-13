# ADR-0011: Asynchronous event processing with at-least-once delivery

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
An employee change must be propagated to several external applications (Slack, Google
Workspace, payroll, more later). In Phase 4 an administrator could run one connector
operation at a time, synchronously, from the API. Phase 5 must make propagation automatic.
External APIs are slow, rate-limited and sometimes down.

## Problem
Where and when should the external calls happen, and what delivery guarantee should the
system be designed around?

## Considered alternatives
| Option | Assessment |
|---|---|
| Call every external application inside the API request | Simple; but the admin waits for every vendor, one broken vendor fails or times out the HR change, and a crash halfway leaves no record of what was done. |
| Fire-and-forget background thread in the API process | No waiting; but work is lost on restart, nothing records progress, and it cannot scale separately. |
| **Durable events processed by separate workers** | The API commits and returns; workers do the external work, record every step, retry later (Phase 6) and scale independently. More moving parts. |

For the guarantee:

| Option | Assessment |
|---|---|
| At-most-once (ack on receipt) | A crash loses work: an employee might never get accounts, or never lose access. Unacceptable for access management. |
| "Exactly-once" | Not achievable end to end across a broker, a database and third-party APIs; claiming it would be misleading. |
| **At-least-once + idempotent processing** | Messages may repeat; processing is made safe to repeat. Honest and achievable. |

## Decision
- The API records events durably (transactional outbox, [ADR-0012](0012-transactional-outbox.md))
  and never calls external applications as part of an employee change.
- Workers ([ADR-0010](0010-redis-and-celery-for-background-work.md)) process events with
  **at-least-once delivery**. Processing is idempotent:
  - an atomic **claim** with a **lease** (`locked_until`) lets one worker own an event;
    duplicates of finished or owned events are skipped;
  - **one execution per (event, workflow)** (unique constraint); redelivery resumes it;
  - **finished steps are never repeated**; `create_user` treats an existing account link as
    done;
  - the relay re-dispatches events whose lease expired and resets abandoned ones to `pending`.
- Workers act on the employee's **current** state, not on the values stored in the event, so
  a late event never grants access to someone already terminated.

## Trade-offs
- Eventual consistency: external applications are updated seconds after the change (about
  a second in the live runs), not within the request. The UI (Phase 8) must show sync status.
- More processes to run and monitor (relay, workers, Redis).
- One gap remains until Phase 6: a crash after an external application created an account
  but before SyncForge stored the link makes the resumed `create_user` fail with "already
  exists". Idempotency keys towards external APIs close it.
  *Update (Phase 6): closed for applications that honour idempotency keys (the mocks do);
  for the real Slack and Google APIs the window produces a visible conflict and a
  dead-letter entry - see ADR-0015 and [reliability.md](../reliability.md#6-idempotency).*

## Consequences
- Every step's status is queryable (`GET .../events/{id}`), which Phase 6 (retries, dead
  letters) and Phase 8 (dashboard) build on.
- Tests prove duplicate delivery, live-lease protection and crash recovery
  (`test_workflow_engine.py`, `test_celery_worker.py`).
- Per-employee ordering across several workers is not guaranteed; acceptable because steps
  read current state. Documented as a future improvement.
