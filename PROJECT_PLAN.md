# SyncForge - Project Plan

| Phase | Deliverable |
|---|---|
| 1 | Development environment, repository setup |
| 2 | Backend foundation, JWT auth, organizations, roles, tenant isolation |
| 3 | Employee management and lifecycle events |
| 4 | Connector framework + mock Slack / Google Workspace / payroll |
| 5 | Workflow engine, transactional outbox, Redis + Celery workers |
| 6 | Reliability: backoff + jitter, idempotency, DLQ, replay, 429, circuit breaker |
| 7 | Data integrity, conflict resolution, audit logging |
| 8 | Angular frontend and dashboard |
| 9 | Security hardening, observability, /api/v2, QA, measured performance |
| 10 | Docker Compose, GitHub Actions CI, final docs, case studies, interview prep |

## Key decisions

- Slack and Google Workspace connectors follow the official API shapes but call local mock
  services; they are labelled simulated unless tested with real credentials.
- Super Admin is platform-wide; all other roles are scoped to one organization.
- Redis is only the transport; durability comes from the PostgreSQL outbox
  (at-least-once delivery, idempotent consumers - no exactly-once claims).
- Python 3.10 also exists on this machine; the project always uses 3.13 via `py -3.13`
  and a virtual environment.
