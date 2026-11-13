# Phase 10 - Docker, CI/CD, deployment and final delivery: plan

Status: plan, 2026-11-13. Starting point: commit `ec0dfa8` (Phase 9 complete: 579
backend tests, 60 frontend unit tests, 13 browser tests).

## 1. Objectives

1. One command starts the whole application in containers, with health checks, a
   persistent database and correct start-up order, without changing the existing
   virtual-environment workflow.
2. Every push to GitHub is checked automatically: lint, tests, migrations, build.
3. A deployment guide that is honest about the difference between local Docker and
   production.
4. The remaining documents: overview and requirements, design decisions, interview
   preparation, future improvements, ten case studies tied to real code and tests.
5. A clean-machine run of the README and the final engineering report.

## 2. Design decisions

| Decision | Choice | Why |
|---|---|---|
| One backend image | The API, worker, relay and migration job run from the same image with different commands | One build, identical code everywhere; the roles differ only in their command |
| Migrations | A one-shot `migrate` service that the API, worker and relay wait for (`service_completed_successfully`) | Never create tables at application start-up (project rule); no race between replicas |
| Frontend serving | Multi-stage build: Node builds the Angular app, nginx serves it and forwards `/api`, `/health`, `/ready`, `/docs`, `/openapi.json` to the API | One origin for the browser (same as the dev proxy), so no CORS and the API port need not be published |
| Client IP behind nginx | Uvicorn `--proxy-headers --forwarded-allow-ips=*`, with the API port **not** published: only nginx can reach it | Sign-in limits see real client addresses (docs/15 section 4a); trusting forwarded headers is safe only because nothing else can connect |
| Existing workflow | The new services are in a Compose profile `full`; plain `docker compose up -d` still starts only PostgreSQL and Redis | The documented venv workflow keeps working unchanged |
| Non-root containers | Backend and mock images run as an unprivileged user | Least privilege |
| Verification | The workspace cannot pull from Docker Hub (network policy). Compose files are validated with `docker compose config`, each image's build and start commands are run in clean environments here, and the containers themselves are verified on the owner's Windows machine with Docker Desktop | Stated plainly; nothing is claimed as verified that was not run |

## 3. Milestones

| # | Scope |
|---|---|
| 1 | Dockerfiles (backend, frontend, mock services), `.dockerignore` files, nginx config, Compose profile `full` with health checks and start-up order; README and docs updates |
| 2 | GitHub Actions: backend (ruff, migrations check, pytest with PostgreSQL and Redis services), frontend (lint, format, API check, unit tests, build), Docker image build; no secrets |
| 3 | `docs/17-deployment-guide.md` |
| 4 | Documents 01-04, 20, 22, 23, 24 (ten case studies) |
| 5 | Clean-machine verification from a fresh clone, final engineering report, final commit and push instructions; then the owner is told that all ten phases are complete |

## 4. Acceptance criteria

- `docker compose --profile full up -d --build` starts PostgreSQL, Redis, migrations,
  API, worker, relay, three mocks and the web app; all report healthy; sign-up, a hire
  provisioned through the mocks, and the dashboard work at `http://localhost:8080`.
- Stopping and starting the stack keeps the data; a stopped worker is reported stale and
  its events complete after it returns.
- CI runs on push and pull request and passes on `main`.
- Documentation describes only what exists; every case study cites real code and tests.
