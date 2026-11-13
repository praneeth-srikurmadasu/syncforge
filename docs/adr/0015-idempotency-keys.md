# ADR-0015: Idempotency keys - outgoing on external creates, incoming on POST /employees

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
SyncForge processes at-least-once (ADR-0011). Retries (ADR-0013) and replay (ADR-0014)
repeat external calls on purpose. Repeating `update_user` or `deactivate_user` is harmless:
they set state. Repeating `create_user` is not. Phase 5's account link covers repeats after
the link was stored, but not a crash or timeout *after the application created the user and
before SyncForge stored the link*. Separately, an API client that loses a response cannot
know whether `POST /employees` happened, and resending it would hire the person twice -
and onboard them twice.

## Problem
How to make repeated creates safe in both directions without distributed transactions.

## Considered alternatives
| Option | Assessment |
|---|---|
| Rely on the external application's uniqueness (409 "already exists") | Turns a harmless repeat into a failure and a dead-letter entry. |
| "Find before create" (look the user up by email after an uncertain attempt) | Works with any API but needs a search operation per connector and careful matching; adopting the wrong account is a security risk. Kept as a future option for APIs without key support. |
| Distributed transaction / two-phase commit with the vendor | Not offered by SaaS APIs. |
| **Idempotency keys** (the convention of payment APIs; IETF Idempotency-Key header draft) | The caller names the intended effect; the server executes it once per key. |

## Decision
- **Outgoing:** the engine sends `Idempotency-Key: syncforge-job-<job id>` on `create_user`.
  Derived from the job, it is identical across attempts and replays of one step and unique
  otherwise. The mock services honour it (replay the stored 2xx response with
  `Idempotent-Replayed: true`; `422` for a reused key with a different body; `409
  idempotency_key_in_use` while the first request runs, classified as retryable
  `in_progress`). Real Slack SCIM and Google Directory do not document the header; this is
  stated in [connectors.md](../connectors.md) and [reliability.md](../reliability.md#6-idempotency).
- **Incoming:** `POST /employees` accepts an optional `Idempotency-Key`. The response is
  stored in `idempotency_records` in the **same transaction** as the employee
  (`before_commit` hook). Same key and body: stored response; different body: `422
  idempotency_key_reused`; failures are not stored; concurrent duplicates resolve through
  the unique constraints and return the winner's response. Keys are scoped to (organization,
  user) and expire after `IDEMPOTENCY_TTL_HOURS` (24); `python -m app.cli purge-expired`
  deletes expired rows.

## Trade-offs
- The outgoing protection is only as good as the external API's support; against the real
  Slack/Google the remaining gap produces a visible conflict, not a duplicate.
- Stored responses contain employee data for up to the TTL; they are scoped to the user who
  created them and deleted on expiry.
- Only one incoming endpoint takes keys today; other creates are protected by uniqueness
  rules that answer repeats with `409`.

## Consequences
- `test_a_worker_crash_after_the_external_create_does_not_create_a_second_account` and
  `test_a_timed_out_create_is_retried_safely` show one account / one record after crashes
  and timeouts.
- `test_a_retried_create_returns_the_first_response_and_creates_nothing` shows one employee
  and one event for a resent request.
