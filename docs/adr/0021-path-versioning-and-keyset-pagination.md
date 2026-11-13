# ADR-0021: Path-based API versions; v2 employee list with keyset pagination

- **Status:** Accepted
- **Date:** 2026-11-13

## Context
All endpoints have lived under `/api/v1` since Phase 2. The project needs a real example
of evolving the API without breaking existing clients (the Angular app, scripts, future
integrations). The employee list is the endpoint most likely to be walked in full by
integrations, and its OFFSET paging shifts pages when employees are hired or archived
while a client pages, and costs more the deeper the page.

## Problem
How to introduce a change that existing clients cannot absorb (a new response envelope
and paging model), and what that change should be.

## Considered alternatives
| Option | Assessment |
|---|---|
| Change `/api/v1/.../employees` in place | Breaks the Angular app and any script reading `items` / `total` / `offset`. |
| Version by header (`Accept: application/vnd.syncforge.v2+json`) or query parameter | Works, but invisible in URLs and logs, easy to forget in tools, harder to route and cache. |
| Add `cursor` as an optional parameter to v1 next to `offset` | No break, but two paging models in one contract, and `total` would still be computed on every call (the expensive part). |
| **Path version: `/api/v2/.../employees` with keyset pagination; v1 unchanged** | Explicit, testable side by side, clients migrate per endpoint. |

## Decision
- Versions are path prefixes. Additive changes go into the current version; breaking
  changes create a new version containing only the endpoints that changed.
- `GET /api/v2/organizations/{id}/employees`: same filters and representation as v1;
  envelope `{data, page: {limit, next_cursor, has_more}}`; keyset pagination over a
  unique sort key ending in the ID; opaque base64url cursor carrying the sort, the last
  key and a fingerprint of organization and filters, refused (`422 invalid_cursor`) when
  reused with a different query. No total count.

## Trade-offs
- No total and no "jump to page N" in v2; the Angular directory, which shows both, stays
  on v1.
- Only three sorts in v2 (each needs a total order ending in the ID).
- Two versions of one endpoint to test and document until v1's list is retired.
- The cursor is not signed; it only encodes a position inside the caller's own
  organization, so tampering cannot reveal anything new, and it is validated.

## Consequences
- Integrations can walk the whole directory without duplicates or gaps while it changes
  (`test_inserts_and_removals_before_the_position_do_not_shift_later_pages`).
- The repository has one filter builder shared by both versions, so v1 and v2 cannot
  drift in what they match.
- Policy and migration guide: docs/08 section 14.
