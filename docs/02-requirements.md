# 02 - Requirements specification

The project brief (a master prompt with modules A-J and a strict ten-phase delivery plan)
is the source of the requirements. This document states the scope as built, the
constraints, the assumptions made, and how ambiguous or conflicting points in the brief
were resolved. Detailed requirements: [03 Functional](03-functional-requirements.md) and
[04 Non-functional](04-non-functional-requirements.md).

## 1. Goal

A realistic, working, tested and documented integration platform that its author can
demonstrate and explain in a software-engineering interview: not a CRUD demo, but an
event-driven system with reliability, data integrity, security and observability.

## 2. Stakeholders

| Stakeholder | Interest |
|---|---|
| Organization administrators | Accounts created, changed and removed correctly and on time |
| Integration managers | Connectors and workflows that are easy to configure and to repair when something fails |
| Security and compliance | No orphaned access after termination; an audit trail; protected credentials |
| Engineers operating it | Clear failure signals, safe retries, reproducible deployments |
| The project owner | A system they can run, demonstrate and defend in detail |

## 3. Scope

**In scope (built):** modules A-J of the brief - authentication and organizations,
employees, connector framework with three connectors, workflows, event processing,
reliability, data integrity and audit, observability, developer API with versioning -
plus the Angular application, Docker images and Compose, CI, and documentation.

**Out of scope (by decision):**

| Item | Reason |
|---|---|
| Real Slack / Google tenants | Paid or organization-owned accounts are not available; the brief allows documented mocks |
| Microservices | The brief asks for a modular monolith unless justified (ADR-0001) |
| Production deployment | The brief asks for a guide, not a deployment, and forbids presenting local Docker as production |
| Parallel workflow steps | Version 1 is sequential by the brief; the design for parallel steps is in docs/11 section 6 |
| MFA, invitations, OAuth authorization-code flow, retention jobs | Listed as future improvements (docs/23) |

## 4. Constraints

- Technology fixed by the brief: Angular, FastAPI, Pydantic, SQLAlchemy, Alembic,
  PostgreSQL, Redis, Celery (or a justified alternative), JWT, pytest, Playwright,
  Docker, GitHub Actions.
- Development machine: Windows 11 with Docker Desktop; all instructions in PowerShell.
- No real secrets in the repository; placeholders in `.env.example`.
- Nothing is published or pushed without the owner's approval.
- Every claim must be backed by a run: no invented test results or performance figures.

## 5. Assumptions

- SyncForge is the HR system of record for the fields it manages; other applications are
  targets, and differences are recorded as conflicts rather than overwritten.
- Workforce changes happen at human rates (hundreds per hour, not thousands per second);
  the design favours correctness and visibility over raw throughput.
- An external application may be slow, rate-limited or down for minutes; work must wait
  and resume without duplicates.
- Organizations are independent tenants sharing one deployment.

## 6. Ambiguities and conflicts in the brief, and their resolution

| Point | Resolution |
|---|---|
| "Exactly once" is implied by "duplicate event processing is safe" | Designed and documented as at-least-once delivery with idempotent consumers; no exactly-once claim (ADR-0011, docs/09 section 7) |
| Two phase numberings (master plan 0-11, strict plan 1-10) | The strict ten-phase plan was followed (CHANGELOG.md, one section per phase) |
| "Use official APIs and OAuth for real integrations" versus no tenants available | Adapters follow the official API shapes (Slack SCIM, Google Directory, OAuth token exchange) against faithful mocks; clearly marked "Simulated" in API and UI |
| Angular Material "or a consistent custom component system" | A small custom design system on CSS tokens (ADR-0020), for density and accessibility control |
| Celery on Windows | Celery's prefork pool does not work on Windows; local runs use `--pool=solo`, containers use prefork (docs/09) |
| Password length | The brief asks for "standard rules"; the minimum was set to 8 at the owner's request, with a common-password check (NIST SP 800-63B blocklist) instead of composition rules (docs/15 section 3) |
| "Retry performed" audit entries for every attempt versus audit volume | Retries are audited as `sync.retry_scheduled`; individual attempts are in `synchronization_attempts` |
| "Rate limiting where appropriate" | Implemented for sign-in and registration (docs/15 section 4a) and per connector towards external applications (ADR-0016) |
| A separate `failed` event status | Not added: a step that fails for good moves the event to `dead_letter` immediately, so "failed" and "waiting for a person" are the same state, and it is always visible and replayable. Retryable failures are `retrying` |
| `/api/v2` "for at least one API" | The employee list with cursor pagination, a genuinely breaking change (ADR-0021) |

## 7. Acceptance

Each phase had acceptance criteria, checked before the phase was closed. The final
acceptance criteria of the brief are checked in the
[final engineering report](FINAL_ENGINEERING_REPORT.md).
