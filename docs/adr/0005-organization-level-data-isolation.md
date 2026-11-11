# ADR-0005: Organization-level data isolation

- **Status:** Accepted
- **Date:** 2026-11-11

## Context
SyncForge is multi-tenant: many organizations share one deployment and one database. Users of
one organization must never read or change another organization's data - employees,
connectors, credentials, events. A single missed check would be a data breach.

## Problem
Choose how tenant data is separated and how every request is confined to the caller's
organization.

## Considered alternatives
| Option | Assessment |
|---|---|
| Database per tenant | Strongest separation, but migrations, connections and backups multiply per tenant; heavy for this scale. |
| Schema per tenant (PostgreSQL schemas) | Good separation, but every migration runs N times and cross-tenant admin queries get complex. |
| PostgreSQL Row-Level Security (RLS) | Enforced by the database itself; requires setting a per-connection tenant variable reliably and complicates pooling and debugging. |
| **Shared tables + `organization_id` + one central access check** | Simple operations and migrations; isolation is enforced in application code, so it must be centralised and heavily tested. |

## Decision
Use **shared tables keyed by `organization_id`**, with isolation enforced in one place:

1. Tenant-scoped routes live under `/api/v1/organizations/{organization_id}/...`.
2. Each route declares a permission via `require_org_permission(...)`.
3. `resolve_org_access` loads the organization and the caller's membership and returns an
   `OrgContext`, or raises `404` (not a member / not visible) or `403` (role lacks permission).
4. Services and repositories receive the organization from `OrgContext` and filter every query
   by its ID.

## Trade-offs
- Isolation depends on application discipline: a new endpoint that forgets the dependency, or a
  query that forgets the `organization_id` filter, would leak data. Mitigated by the single
  dependency, code review, and cross-organization tests for every tenant-scoped resource.
- Returning 404 instead of 403 to outsiders makes debugging slightly harder, in exchange for
  not revealing which organization IDs exist.

## Consequences
- Every later tenant-scoped feature (employees, connectors, workflows, events) must add a test
  proving another organization's member gets `404`.
- RLS remains a possible future defence-in-depth layer on top of the application check.
- UUID primary keys mean IDs cannot be guessed by incrementing numbers.
