# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-13

First complete release. It was built in ten phases; the commit history shows each step.

### Added

- **Identity and tenancy:**
  - registration, JWT sign-in, and logout with server-side revocation;
  - organizations with four roles and a permission matrix;
  - isolation enforced in queries and by composite foreign keys.
- **Workforce:**
  - employees and departments with search, filters, sorting and pagination;
  - reporting lines with cycle prevention;
  - termination (direct reports move up) and archiving;
  - lifecycle events.
- **Connectors:**
  - an adapter framework with Slack, Google Workspace (OAuth token lifecycle) and payroll
    adapters, all verified against local simulated services;
  - encrypted credentials, error normalization, timeouts and an SSRF allowlist.
- **Workflows and events:**
  - configurable workflows;
  - a transactional outbox, outbox relay and Celery workers;
  - at-least-once delivery with leases and idempotent steps.
- **Reliability:**
  - failure classification;
  - exponential backoff with jitter and `Retry-After`;
  - a dead-letter queue with authorized replay;
  - a circuit breaker and rate limits per connector;
  - idempotency keys for external creates and `POST /employees`.
- **Data integrity:**
  - an append-only audit log;
  - optimistic concurrency with ETag / `If-Match`;
  - field-level source-of-truth policies, reconciliation and conflict resolution.
- **Security hardening:**
  - sign-in rate limits and a common-password check;
  - an append-only sign-in history;
  - a request size limit and security headers.
- **Observability:**
  - JSON logs with request and correlation IDs;
  - health and readiness probes;
  - worker and relay heartbeats;
  - platform status and an organization summary with processing percentiles.
- **API:** `/api/v1`, plus a `/api/v2` employee list with cursor pagination.
- **Angular administration application:**
  - 16 areas and role-aware navigation;
  - light and dark themes, phone layouts, and accessibility checks.
- **Delivery:**
  - Docker images and a full-stack Docker Compose profile;
  - GitHub Actions CI running linting, migration checks, all tests, and browser tests
    against the containers.
- **Measured performance baseline**, and an employee index chosen from the measurements.
