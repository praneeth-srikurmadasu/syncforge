# ADR-0007: Advisory lock for reporting-line changes

- **Status:** Accepted
- **Date:** 2026-11-11

## Context
Employees form a reporting tree through `manager_id`. A cycle (A reports to B, B reports to
A, or longer) would break every "walk up the chain" operation and would be synchronized to
external systems. The service rejects a manager change if the employee already appears in
the new manager's management chain (one recursive query).

## Problem
The check-then-write is not safe under concurrency. Request 1 sets "Bob reports to Alice"
while request 2 sets "Alice reports to Bob". Each locks only its own employee row, each sees
a chain without a cycle, and both commit: a cycle is created. Row locks cannot help because
the two requests lock different rows.

## Considered alternatives
| Option | Assessment |
|---|---|
| Row locks on the employee and the new manager | Does not cover longer chains (A -> B -> C): the conflicting rows are not known in advance. |
| `SERIALIZABLE` isolation for these transactions | Correct, but conflicts surface as serialization failures that every caller must retry; harder to reason about. |
| Lock the whole `employees` table | Correct but blocks unrelated writes in every organization. |
| Store the tree as a materialized path / closure table | Makes cycle checks cheap but adds a second structure to keep consistent; premature at this scale. |
| **Transaction-scoped advisory lock per organization** | Serializes only manager changes, only within one organization; released automatically at commit or rollback. |

## Decision
Before validating a manager change, take `pg_advisory_xact_lock(key)`, where `key` is a
64-bit integer derived from the organization's UUID. This applies to:

- `PATCH /employees/{id}` when the body contains `manager_id`;
- `POST /employees/{id}/terminate`, which moves the terminated employee's direct reports.

## Trade-offs
- Manager changes within one organization run one at a time. They are rare, short
  transactions, so contention is negligible. Other updates (name, location, department) do
  not take the lock.
- Two organizations could in theory map to the same 64-bit key; the only effect would be
  that they occasionally serialize with each other, never incorrect results.
- The lock is a PostgreSQL feature; acceptable because PostgreSQL is the system of record
  (ADR-0002).

## Consequences
- `test_simultaneous_manager_changes_cannot_form_a_cycle` runs the race with two real
  database sessions: the second request waits, then re-checks and gets `422 manager_cycle`.
  The test fails if the lock is removed.
