# ADR-0013: Retries with exponential backoff, jitter and a bounded budget

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
Phase 5 attempted each workflow step once: a single 503 from Slack failed the whole
onboarding. Most failures of SaaS APIs are transient (incidents, deployments, 429s during
bursts), so a step that fails now very often succeeds a few seconds later. Other failures
(401, 403, invalid data, a disconnected connector) never succeed by repetition.

## Problem
When, how often and for which failures should a step be tried again - without hammering a
struggling application, without tying up workers while waiting, and without retrying
forever?

## Considered alternatives
| Option | Assessment |
|---|---|
| No retries; a person replays every failure | Every blip becomes manual work. |
| Fixed interval (e.g. every 5 s) | Too slow for blips or too aggressive for outages; synchronized clients retry in lock-step. |
| Exponential backoff without jitter | Spreads attempts over time, but jobs that failed together retry together ("thundering herd"). |
| Celery's built-in `autoretry_for` / `countdown` | Retry state lives in the broker message; lost with the message (Redis runs without persistence), invisible in the database, and the whole task re-runs rather than one step. |
| **Exponential backoff with proportional jitter, honouring `Retry-After`, bounded attempts, scheduled as data in PostgreSQL** | Fast for blips, gentle for outages, de-synchronized, visible, survives restarts. |

## Decision
- **Classify first.** Only `server`, `timeout`, `network`, `rate_limited`, `in_progress`
  and `circuit_open` failures are retryable; all others fail the step at once.
- **Delay** after attempt *n*: `min(max_delay, max(base * 2^(n-1) * uniform(1-j, 1+j), Retry-After))`,
  defaults base 2 s, jitter 0.2, maximum 300 s.
- **Budget:** `RETRY_MAX_ATTEMPTS` (default 5, first attempt included) per step per round;
  a replay from the dead-letter queue starts a new round.
- **Scheduling as data:** a failed step becomes `retrying` with `next_attempt_at`; the
  event becomes `retrying` with the earliest such time. The outbox relay re-dispatches due
  events; nothing sleeps in a worker. Later steps of the execution wait.
- **History:** every external call is a `synchronization_attempts` row, opened before and
  closed after the call (`interrupted` if the worker died).

## Trade-offs
- Retry timing has the relay's poll interval (1 s) as extra latency.
- Jitter makes exact retry times non-deterministic; tests seed the random generator or
  assert ranges.
- Proportional jitter (+/-20 %) de-synchronizes less than "full jitter" (uniform 0..delay)
  but keeps attempt order predictable and delays explainable.
- The defaults give about 30 s from first failure to giving up - enough for blips, not for
  long outages; long outages end in the dead-letter queue by design (ADR-0014).

## Consequences
- A transient 503 no longer fails an onboarding (`test_a_transient_failure_is_retried_after_a_backoff_and_then_succeeds`).
- Permanent errors reach a person immediately (`test_permanent_failures_are_not_retried`).
- The attempts endpoint answers "what happened, when, and why" for every step.
- The live demonstration found a READ COMMITTED race between the relay and the worker's
  claim, fixed by making due `retrying` events claimable (docs/12, section 9).
