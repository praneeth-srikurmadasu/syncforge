# ADR-0008: Connector adapter pattern with a registry

- **Status:** Accepted
- **Date:** 2026-11-11

## Context
SyncForge must provision, update and deactivate users in several external applications
(Slack, Google Workspace, payroll now; more later). Each has its own API style,
authentication and error format. The workflow engine (Phase 5) and the retry engine
(Phase 6) must work with all of them.

## Problem
How to integrate many vendors without spreading vendor-specific code, and duplicated
business rules, through the event-processing core.

## Considered alternatives
| Option | Assessment |
|---|---|
| Vendor `if/else` branches inside the services and workers | Fast to start; every new vendor touches the core, rules get duplicated per branch, testing explodes. |
| A generic "HTTP request template" engine configured in the database | Flexible for simple cases, but vendor auth flows (OAuth token refresh), pagination and error formats still need code; it moves complexity into untyped config. |
| Third-party integration platform / unified API SDK | Less code, but adds a paid external dependency and hides the engineering this project needs to demonstrate. |
| **Adapter per vendor behind one interface, looked up in a registry** | Vendor code is isolated and typed; the core depends only on the interface; new vendors are additive. |

## Decision
- One abstract `Connector` interface with five operations: `test_connection`,
  `create_user`, `update_user`, `deactivate_user` and `get_user`. Inputs and outputs are
  vendor-neutral (`UserProfile`, `ExternalUser`).
- Every adapter declares a `ConnectorSpec`:
  - type and semantic version;
  - auth type;
  - a simulated flag;
  - Pydantic models for its config and credentials.
- Adapters register with `@register`. The service builds them through
  `registry.build_connector`, which validates settings, checks the major version and
  injects the shared `ConnectorHttpClient`.
- Vendor failures are normalized to one `ConnectorError` with a category and a
  `retryable` flag.
- Business rules stay in `ConnectorService`, once for all vendors:
  - permissions;
  - tenant checks;
  - account links;
  - "no account for terminated employees".

## Trade-offs
- The interface is the lowest common denominator; vendor-specific features (Slack user
  groups, Google org units) need interface extensions or adapter-specific config.
- One more layer of indirection when reading the code.

## Consequences
- Adding a connector touches only its adapter module, `Settings` (default URL) and tests;
  [connectors.md](../connectors.md#7-adding-a-connector) has the checklist.
- The same parametrized tests run against every adapter, which proves the interface holds.
- Phase 5 workflows reference connectors by ID and call the interface; Phase 6 reads
  `ConnectorError.retryable` and `retry_after` without knowing the vendor.
