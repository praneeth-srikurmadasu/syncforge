# ADR-0017: An append-only audit log written in the same transaction as each change

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
An enterprise integration platform must answer "who did what, when, and with what result":
who gave someone admin rights, who rotated a connector's credentials, why an onboarding
failed. Structured logs exist (Phase 2) but are operational: they rotate, are not scoped to
an organization, and a change can be logged without having committed (or commit without
being logged).

## Problem
How to record important actions so that the record is complete, trustworthy, free of
secrets and personal values, and readable per organization.

## Considered alternatives
| Option | Assessment |
|---|---|
| Use the application logs | Not per organization, not queryable through the API, no guarantee that a logged change committed. |
| SQLAlchemy event listeners recording every row change automatically | Captures columns, not intent ("member.role_changed from viewer to admin"); records personal values by default; hard to keep secrets out. |
| PostgreSQL triggers writing history tables | Complete, but knows nothing about the actor (a pooled database user) or the request. |
| A separate audit service / message stream | Another component, and a second write that can diverge from the change (the problem the outbox solved for events). |
| **Explicit `audit.record()` calls in services, in the same transaction; a trigger forbids UPDATE/DELETE** | Records intent with chosen details, atomic with the change, actor from the request, tamper-resistant. |

## Decision
- `audit_logs` (migration `0010`): organization, actor type (`user`/`system`), actor user
  ID, action, resource type and ID, outcome, JSON details, request ID, time; no foreign key
  to organizations (history outlives the organization).
- Services call `app/audit.py` `record()` before their commit; the engine and the circuit
  breaker do the same for system actions. The actor comes from `session.info`, set by the
  authentication dependency; sessions without it are the system.
- Details carry IDs, changed field names, error categories; values only for non-personal
  fields; never secrets or payloads.
- A trigger refuses UPDATE (except the actor's `ON DELETE SET NULL`) and DELETE (except
  inside a transaction that sets `syncforge.allow_audit_delete = 'on'`, reserved for a
  retention job).
- `GET .../audit-logs` with filters; permission `audit:read` (Org Admin, Integration Manager).

## Trade-offs
- Explicit calls can be forgotten when a new action is added; tests per area and review
  are the safeguard (an automatic listener would not record intent).
- One extra INSERT per audited change, in the same transaction.
- No audit of login/logout (not organization-scoped) - Phase 9 candidate.
- No retention job yet; the table grows with activity.

## Consequences
- Every permission change, connector change, workflow execution outcome, retry, dead
  letter, replay, circuit transition and conflict decision is traceable, with the request ID
  linking to the logs.
- `test_entries_cannot_be_updated` shows that even direct SQL cannot rewrite history.
