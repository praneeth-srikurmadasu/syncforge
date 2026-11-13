# Contributing to SyncForge

How to set up the project, make a change, and get it merged. The rules here are the ones
the project has followed since Phase 1.

## Set up

Follow the README: **Quick start** for the virtual-environment workflow (Python 3.13,
Node 22, Docker Desktop for PostgreSQL and Redis), or **Run everything in Docker**.
Copy `.env.example` to `.env`; never commit `.env`.

## Making a change

1. Create a branch from `main`: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`.
2. Keep the layering: routers in `app/api` only translate HTTP; business rules live in
   `app/services`; queries in `app/repositories`; SQLAlchemy models in `app/models`;
   request and response contracts in `app/schemas`. Frontend pages own their data and
   call the typed services in `core/api`; shared components only present.
3. Every query on organization data filters by `organization_id`; every endpoint checks a
   permission with `require_org_permission` (docs/15 section 9).
4. Write tests with the change (section "Tests").
5. Update the documentation the change affects, in the same pull request. Document only
   what exists.

## Database changes

- Change the models, then create a migration: `alembic revision --autogenerate -m "..."`,
  and read the generated file before committing (name constraints, check server
  defaults, write a working `downgrade`).
- `alembic check` must report no drift; the test suite also downgrades to base and
  upgrades again.
- Migrations must be backward compatible with the running release (expand first,
  contract later; docs/17 section 7). Never create tables at application start-up.

## API changes

- Additive changes stay in `/api/v1`; breaking changes need a new version
  (docs/08 section 14).
- After any API change, refresh the frontend's contract: regenerate
  `frontend/openapi/openapi.json` and the types with the commands in `frontend/README.md`
  ("API types"), then run `npm run api:check`. CI fails if they drift.

## Tests

| Change | Add |
|---|---|
| Business rule | A test in `backend/tests` against the real database |
| New endpoint | API tests for success, validation, permissions and organization isolation |
| Concurrency-sensitive code | A two-session test (see `test_concurrency.py`) |
| Connector behaviour | An adapter test against the mock service, including failure responses |
| Frontend logic | A Vitest spec next to the component or service |
| User journey | A Playwright test in `frontend/e2e/tests` |

A test that fails intermittently is a bug: investigate it, do not add retries.

## Before you open a pull request

From `backend/`:

```powershell
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m pytest -q
```

From `frontend/`:

```powershell
npx ng lint
npm run format:check
npm run api:check
npm run test:ci
npx ng build
```

CI runs the same checks plus the Docker stack with the browser tests
(`.github/workflows/ci.yml`); a pull request is merged only when CI is green.

## Commit messages

Conventional commits, imperative mood, one subject line under about 72 characters, then
bullet lines for the details:

```
feat(connectors): add an Okta connector

- Adapter, registry entry and mock service
- Adapter tests including 401, 429 and timeouts
```

Types used in this repository: `feat`, `fix`, `test`, `docs`, `perf`, `build`, `ci`,
`chore`, `refactor`.

## Security

- Never commit secrets, real credentials, tokens or `.env` files. `.env.example` holds
  placeholders only.
- Never log passwords, tokens, credentials or personal values; log IDs.
- Report a vulnerability privately to the maintainer instead of opening a public issue.

## Documentation

`docs/` is numbered by topic (01-24) with ADRs in `docs/adr/`. A decision that is hard to
reverse or rejects a reasonable alternative gets a new ADR; existing ADRs are not edited
to change their decision. Record actual results only: no invented figures.
