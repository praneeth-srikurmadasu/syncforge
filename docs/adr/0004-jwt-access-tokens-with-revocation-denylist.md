# ADR-0004: JWT access tokens with a revocation denylist

- **Status:** Accepted
- **Date:** 2026-11-11

## Context
The API is consumed by an Angular single-page app (Phase 8) and by scripts. Users must be
able to log out, and disabling a user must stop their access immediately.

## Problem
Choose how clients authenticate and how sessions end.

## Considered alternatives
| Option | Assessment |
|---|---|
| Server-side sessions + cookie | Easy revocation, but cookies bring CSRF handling and are awkward for non-browser clients. |
| Stateless JWT only | No database lookup per request, but "logout" only deletes the token on the client — a copied token keeps working until it expires. |
| **JWT + `jti` denylist** | Signed, self-describing tokens; logout stores the token's `jti`; each request does one primary-key lookup. |
| Opaque tokens stored in DB | Simple revocation, but a lookup is required for all token data, not just revocation. |

## Decision
Issue short-lived (default 30 min) **HS256 JWTs** with `sub`, `jti`, `iat`, `exp`, `iss`,
`aud` and `type`. Logout inserts the `jti` into `revoked_tokens`. Every protected request
also re-loads the user and rejects inactive accounts.

## Trade-offs
- One indexed lookup on `revoked_tokens` plus one on `users` per request.
- No refresh tokens yet: when a token expires the user logs in again. Refresh tokens are a
  documented future improvement.
- HS256 uses one shared secret; if other services ever need to verify tokens, switch to an
  asymmetric algorithm (RS256/EdDSA) so they only hold a public key.

## Consequences
- Logout is real and per-token: other devices stay logged in.
- Deactivating a user blocks their existing tokens on the next request.
- `revoked_tokens` rows can be deleted after `expires_at`, keeping the table small.
