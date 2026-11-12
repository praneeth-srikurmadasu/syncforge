# ADR-0018: Optimistic concurrency for employees with a version column, ETag and If-Match

- **Status:** Accepted
- **Date:** 2026-11-12

## Context
Employee records are edited through forms (Phase 8 UI) and by integrations. Two editors
working from the same state can silently overwrite each other ("lost update"). Row locks
already serialize simultaneous writes (Phase 3), but they cannot see that a save is based
on a state that is minutes old.

## Problem
Detect that a change was made from an outdated copy, and refuse it instead of overwriting.

## Considered alternatives
| Option | Assessment |
|---|---|
| Last write wins | The lost update. |
| Pessimistic "edit locks" held while a form is open | Locks abandoned by closed tabs; needs expiry and unlock UX. |
| Compare `updated_at` timestamps | Clock resolution and equality problems; not a standard HTTP precondition. |
| Compare all field values sent by the client | Complex; partial updates make it ambiguous. |
| **Integer version per row, exposed as ETag; If-Match precondition; 412 on mismatch** | Standard HTTP (RFC 9110 conditional requests), cheap, unambiguous, works for partial updates. |

## Decision
- `employees.version` (migration `0011`), maintained by SQLAlchemy `version_id_col`
  (incremented on every UPDATE; the UPDATE carries `WHERE version = <read>`).
- Responses include `version` and `ETag: "<version>"`; `PATCH`, terminate and archive
  accept `If-Match`; mismatch -> `412 version_conflict` with expected and current version;
  nothing changes.
- The service locks the row before comparing, making check and write atomic.
- `If-Match` is optional, so existing clients keep working; the UI always sends it.
- Conflict resolution that adopts an external value passes the version recorded at
  detection, so it too refuses to act on outdated information.

## Trade-offs
- Optional precondition: clients that do not send it keep last-write-wins semantics. Making
  it mandatory (428 Precondition Required) is a possible later tightening.
- Only employees have versions today; other resources (connectors, workflows) are edited
  rarely and by few people.

## Consequences
- `test_a_stale_edit_is_refused_and_changes_nothing` and the two-session
  `test_simultaneous_saves_from_the_same_version_let_exactly_one_win`.
- Moving direct reports on termination bumps their versions, so stale edits of them are
  refused too.
