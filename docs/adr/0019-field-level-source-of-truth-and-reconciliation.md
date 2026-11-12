# ADR-0019: Field-level source-of-truth policies, reconciliation that records conflicts, explicit resolution

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
SyncForge pushes HR's employee data to connected applications, but those applications are
also edited directly: an administrator changes a department in Google, a security team
suspends a Slack account, payroll corrects a name. The copies drift. Different
organizations trust different systems for different facts.

## Problem
How to find disagreements, decide which side is right, and fix them - without silently
overwriting data and without inventing a universal source of truth.

## Considered alternatives
| Option | Assessment |
|---|---|
| SyncForge always wins: periodically push everything | Silently destroys deliberate changes made in the applications (e.g. a suspension by the security team). |
| The last writer wins, whichever system | Unpredictable; depends on timing. |
| One global source of truth per application | Too coarse: HR is right about departments, the identity provider about account status. |
| Real-time two-way sync via vendor webhooks | Needs webhook support in every vendor and public endpoints; still needs the policy question answered. |
| **Per-organization, per-field policy (authority, severity, manual/auto); reconciliation records conflicts; resolution is explicit and audited** | No silent overwrites, configurable, explainable, works with read-only `get_user`. |

## Decision
- `data_source_policies`: per organization and field (first/last name, email, department,
  designation, location, account_active): authority = SyncForge or one connector,
  severity, resolution mode. Defaults: HR authoritative, manual, severity by field; a
  terminated person with an active account is always critical.
- Reconciliation per connector reads linked accounts and compares normalized values; each
  difference opens or refreshes one conflict (partial unique index); agreement closes it.
  `auto` mode applies the authoritative value immediately.
- Resolution: `use_syncforge` (push), `use_external` (adopt through the normal versioned,
  audited employee update, which propagates via events), `dismiss` (note). Choosing the
  non-authoritative side needs override and a note; outdated values (`conflict_stale`) and
  unknown departments are refused.
- Permissions: read for everyone, resolve for Integration Managers and Admins (adoption also
  needs `employees:write`), policies for Admins only.

## Trade-offs
- Reconciliation is pull-based and on demand (or scheduled by the operator): conflicts are
  found when it runs, not instantly.
- Seven fields; values are compared as normalized text.
- Conflict rows hold the conflicting values (personal data for names and e-mails),
  visible to members who may see employees; never logged or audited.
- Reactivation and department creation are deliberately not automatic.

## Consequences
- A department changed in payroll is detected, shown with both values and the authority,
  refused when adopted against the policy without override, and fixed by pushing HR's value
  (demo scenario 6; `test_hr_wins_pushes_syncforges_value_to_the_application`).
- Organizations can make an identity provider authoritative for account status
  (`test_an_identity_provider_can_be_authoritative_for_account_status`).
