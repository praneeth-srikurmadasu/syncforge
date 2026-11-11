# ADR-0006: Composite foreign keys for tenant integrity

- **Status:** Accepted
- **Date:** 2026-11-11

## Context
Employees reference other tenant-owned rows: their department and their manager (another
employee). ADR-0005 confines every *request* to one organization, but a reference column is
just a UUID. If a bug ever let an Acme employee point at a Globex department or manager,
Acme's data would silently be linked to another tenant, and later synchronization would push
that link to external systems.

## Problem
Make it impossible to store a reference from one organization's row to another
organization's row, even if application code has a bug.

## Considered alternatives
| Option | Assessment |
|---|---|
| Plain foreign key on `department_id` / `manager_id` + application check | The application check is needed for a good error message anyway, but a missed check (or a future code path) can still write a cross-tenant reference. |
| Trigger that compares organization IDs | Works, but logic hidden in triggers is harder to review, test and migrate. |
| PostgreSQL Row-Level Security | Controls which rows a session sees; does not by itself validate references between rows. |
| **Composite foreign key on `(organization_id, <ref>_id)`** | Declarative, enforced by PostgreSQL on every write, visible in the schema, no extra code. Needs a unique `(organization_id, id)` on the target table. |

## Decision
Reference tenant-owned rows with composite foreign keys that include `organization_id`:

- `employees (organization_id, department_id) -> departments (organization_id, id)`
- `employees (organization_id, manager_id) -> employees (organization_id, id)`

Target tables carry a unique constraint on `(organization_id, id)`. The service layer still
validates references first so clients get a clear `422 department_not_found` /
`manager_not_found`; the constraint is the backstop. If the backstop fires (for example a
department deleted concurrently), the service maps the constraint name to the same 422.

## Trade-offs
- One extra unique index per target table (small; it duplicates the primary key plus a
  UUID column).
- SQLAlchemy relationships need explicit composite join conditions (`Employee.department`,
  `Employee.manager` are defined as view-only relationships).

## Consequences
- Cross-tenant references are rejected by the database: `test_cannot_use_another_organizations_department`
  and `test_cannot_use_another_organizations_manager` insert them directly and expect
  `IntegrityError`.
- Future tenant-owned tables that reference each other (connectors, workflows, events) follow
  the same pattern.
