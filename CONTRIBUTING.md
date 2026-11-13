# Contributing

## Development setup

Requirements: Python 3.13, Node.js 22 LTS, Docker (for PostgreSQL and Redis), and Git.

```bash
cp .env.example .env
# Put a long random value in JWT_SECRET_KEY and a Fernet key in CONNECTOR_ENCRYPTION_KEY:
python -c "import secrets; print(secrets.token_urlsafe(64))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

docker compose up -d postgres redis

cd backend
python3.13 -m venv .venv && source .venv/bin/activate   # Windows: py -3.13 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
```

Then run each process in its own terminal, with the virtual environment active:

| Process | Command (from) |
|---|---|
| API | `uvicorn app.main:app --reload` (`backend/`) |
| Worker | `python -m celery -A app.workers.celery_app worker --loglevel=INFO` (`backend/`; add `--pool=solo` on Windows) |
| Outbox relay | `python -m app.cli outbox-relay` (`backend/`) |
| Simulated applications | `python -m mockservices.run_all` (`mock-services/`) |
| Web app | `npm ci && npm start` (`frontend/`), then http://localhost:4200 |

On Windows, start Python tools as `python -m ...` with the project's interpreter. A bare
`celery` can pick up another project's install from `PATH`.

Useful commands (from `backend/`):
- `python -m app.cli seed-demo --admin-email you@example.com` creates a demo organization
  with 20 employees.
- `python -m app.cli create-superadmin --email ... --name ...` creates a platform admin
  (it prompts for the password).
- `python -m app.cli purge-expired` deletes expired tokens and idempotency records.

## Making a change

1. Branch from `main`: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`.
2. Keep the layers:
   - routers (`app/api`) only translate HTTP;
   - business rules live in `app/services`;
   - queries live in `app/repositories`.

   In the frontend, pages own their data, and shared components only present it.
3. Every query on organization data filters by `organization_id`, and every endpoint
   checks a permission with `require_org_permission`.
4. Add tests with the change, and update the docs it affects. Document only what exists.

**Database changes.** Change the models, run `alembic revision --autogenerate -m "..."`,
and review the generated file: constraint names, defaults, and a working `downgrade()`.
`alembic check` must report no drift. Keep migrations backward compatible with the
running release (expand first, contract later).

**API changes.** Additive changes stay in `/api/v1`, and breaking changes need a new
version. After any API change, refresh `frontend/openapi/openapi.json` and the generated
types (see `frontend/README.md`), then run `npm run api:check`.

| Change | Test to add |
|---|---|
| Business rule or endpoint | A backend test against the real database: success, validation, permissions, organization isolation |
| Concurrency-sensitive code | A two-session test (see `test_concurrency.py`) |
| Connector behaviour | An adapter test against the mock, including failure responses |
| Frontend logic or user journey | A Vitest spec; a Playwright test for a journey |

A test that fails intermittently is a bug. Investigate it instead of adding retries.

## Before opening a pull request

```bash
cd backend && ruff check . && ruff format --check . && pytest -q
cd frontend && npx ng lint && npm run format:check && npm run api:check && npm run test:ci && npx ng build
```

CI runs the same checks plus the browser tests against the Docker stack. A pull request
is merged when CI is green.

## Commit messages

Use conventional commits in the imperative mood:

```
feat(connectors): add an Okta connector
```

Types: `feat`, `fix`, `test`, `docs`, `perf`, `build`, `ci`, `chore`, `refactor`.

## Security

Never commit secrets, real credentials or `.env` files, and never log passwords, tokens
or personal values. To report a vulnerability, see [SECURITY.md](SECURITY.md).
