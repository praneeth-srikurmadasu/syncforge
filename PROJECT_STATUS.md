# SyncForge - Project Status

**Current phase:** 2 - Backend foundation, authentication and organizations
**Last updated:** 2026-11-11

| Phase | Status |
|---|---|
| 1 - Environment and repository | Complete |
| 2 - Backend foundation, auth, organizations | In progress (Parts 1-4 of 5 done) |
| 3-10 | Not started |

## Phase 2 progress

| Part | Scope | Status | Verified on |
|---|---|---|---|
| 1 | FastAPI app, settings, JSON logging, request IDs, error envelope, `/health`, `/ready`, PostgreSQL in Docker | Done | Windows 11, Python 3.13.17, Docker PostgreSQL 16 |
| 2 | Tables `organizations`, `users`, `organization_memberships`; Alembic migration `0001` | Done | same |
| 3 | Argon2id hashing, JWT, register / login / me / logout, `revoked_tokens` (migration `0002`) | Done | same |
| 4 | Organizations API, role permissions, organization isolation, member management, last-admin rule, Super Admin CLI | Done | same |
| 5 | Phase 2 wrap-up: final verification and phase report | Next | |

### Latest verification (actual results)

- `ruff check .` - All checks passed
- `ruff format --check .` - 50 files already formatted
- `python -m pytest` - **111 passed** (includes a two-session row-locking concurrency test)
- Live run: register -> login -> `/me` -> logout -> `/me` returned `401 token_revoked`
- Live run: create org -> add viewer -> viewer rename `403` -> outsider read `404` ->
  last admin self-demotion `409 last_admin`

## Phase 1 verification (Windows 11 machine)

| Tool | Version |
|---|---|
| Python | 3.13.17 (via py launcher; 3.10.5 also installed, not used) |
| pip | 26.2.2 |
| Node.js / npm | 24.18.0 / 11.16.0 |
| Angular CLI / TypeScript | 22.2.6 / 7.0.2 |
| Git | 2.40.1 |
| Docker / Compose | 29.9.3 / v5.7.0 (WSL 2) |
| GitHub CLI | 2.103.3 |

## Known limitations (current)

- Members can only be added if they already registered (no email invitations yet).
- No rate limiting on login/register yet - Phase 9.
- Expired `revoked_tokens` rows are not cleaned up automatically yet - Phase 5.
- No refresh tokens: users log in again after 30 minutes.
