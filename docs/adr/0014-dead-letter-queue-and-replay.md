# ADR-0014: Dead-letter queue in PostgreSQL with authorized, partial replay

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
After classification and retries (ADR-0013) some steps still fail: credentials expired, a
permission was removed, the data is invalid, or an outage outlasted the retry budget. Such
work must not be lost, must be visible, and must be recoverable once the cause is fixed.

## Problem
Where do finally-failed events go, what is kept about them, and how is the work restarted
safely - without repeating the steps that already succeeded and without letting anyone
trigger external calls?

## Considered alternatives
| Option | Assessment |
|---|---|
| Leave them as `failed` events; re-create the employee to retry | Loses the link to the original event; re-creating causes duplicates. |
| A broker-level dead-letter queue (a Redis list / RabbitMQ DLX) | Messages carry only an event ID; the error, the steps and the history live in PostgreSQL anyway. A second store to keep consistent; Redis runs without persistence. |
| Replay = re-run the whole event from scratch | Repeats succeeded steps: duplicate accounts in applications without idempotency support. |
| **A `dead_letter` event status plus `dead_letter_events` entries in PostgreSQL; replay resets only failed (and dependent) steps and requeues through the outbox** | One source of truth, queryable, auditable, safe. |

## Decision
- An event whose execution failed for good ends in status `dead_letter` (replacing
  Phase 5's `failed`); in the same transaction one `dead_letter_events` entry **copies** the
  error (connector, operation, category, code, HTTP status, message, attempts, reason
  `retries_exhausted` | `non_retryable`). A partial unique index allows one open entry per event.
- Endpoints: list and detail need `events:read`; **replay needs the new `events:replay`**
  permission (Integration Manager, Org Admin), because it causes real external calls.
- Replay locks the entry and the event, refuses if already replayed (`409`) or if no failed
  workflow is active (`409 workflow_inactive`), resets failed and never-attempted skipped
  jobs to `pending` with a fresh retry budget (`attempts_at_last_replay`), sets the event to
  `pending`, closes the entry (who, when) and writes an outbox row - one transaction.
- Migration `0007` moves existing `failed` events into the queue with entries built from
  their first failed step.

## Trade-offs
- Replay is per entry; bulk replay ("all entries for connector X") is a future addition
  (the list endpoint already filters by connector).
- Replay processes the event against the *current* configuration (active workflows) and
  employee state, not a snapshot - the right default for access provisioning, but it means
  replay results can differ from the original intent if the configuration changed.
- Entries are never deleted except with their organization (retention: future work).

## Consequences
- Nothing that fails is lost or silent; the dashboard (Phase 8) can show the open queue.
- `test_replay_reruns_only_what_failed_and_completes`: after a replay Slack is not called
  again and exactly one account exists in each application.
- `test_simultaneous_replays_of_one_entry_replay_it_once` proves the locking with two real
  database sessions.
