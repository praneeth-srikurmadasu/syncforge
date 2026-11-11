# SyncForge

**Universal Workforce Integration & Synchronization Platform**

SyncForge keeps employee data consistent across HR, Slack, Google Workspace and payroll by
turning workforce changes (hire, transfer, termination) into reliably processed, audited
synchronization events.

> **Status: Phase 1 of 10 - development environment and repository setup.**
> No application functionality exists yet. See `PROJECT_STATUS.md`.

## Planned stack

| Layer | Technology |
|---|---|
| Frontend | Angular 22, TypeScript, RxJS, Angular Material |
| Backend | Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 16 (Docker) |
| Background jobs | Redis 7 + Celery (Docker) |
| Testing | Pytest, HTTPX, Playwright |
| Tooling | Docker Compose, GitHub Actions |

## Prerequisites (Windows)

Python 3.13 (via `py -3.13`), Node.js 24 LTS, Git, Docker Desktop (WSL 2), VS Code.
PostgreSQL and Redis run in Docker - no local install needed.

## Setup

```powershell
Copy-Item .env.example .env
```

## Repository layout

```
backend/          FastAPI app (Phase 2+)
frontend/         Angular app (Phase 8)
mock-services/    Mock Slack / Google Workspace / payroll APIs (Phase 4)
docs/             Architecture, API, database, ADRs, case studies
infrastructure/   Docker files and scripts
.github/          CI workflows (Phase 10)
```
