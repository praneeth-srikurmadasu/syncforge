# 03 - Functional requirements

Requirements from modules A-J of the brief, numbered, with their status and where they
are implemented and tested. "Done" means implemented, automatically tested, and
documented. Test names refer to `backend/tests/` unless marked "browser" (Playwright,
`frontend/e2e/`) or "unit" (Vitest, `frontend/src`).

## A. Authentication and organizations

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| A1 | Register, log in, log out, current user | Done | `test_auth_api.py` (`test_register_creates_user`, `test_login_returns_bearer_token`, `test_logout_revokes_the_token`, `test_me_returns_user_and_memberships`); browser auth tests |
| A2 | Password hashing | Done | Argon2id, `test_security.py` |
| A3 | JWT authentication with expiry and revocation | Done | `test_me_with_expired_token_returns_401`, `test_logout_only_revokes_that_one_token` |
| A4 | Organizations with creator as admin | Done | `test_create_organization_makes_creator_admin` |
| A5 | Organization-level data isolation | Done | `test_cross_organization_access_is_404_everywhere`, `test_list_shows_only_my_organizations`; browser isolation test |
| A6 | User management (members, roles, removal, last-admin rule) | Done | `test_organizations_api.py`, `test_simultaneous_demotions_cannot_remove_every_admin` |
| A7 | Four roles with permissions | Done | `test_authorization.py`, role matrix in docs/15 section 9; browser viewer test |
| A8 | Sign-in protection (Phase 9) | Done | `test_security_hardening.py`, `test_security_events.py` |

## B. Employee management

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| B1 | Fields: employee ID (number), names, email, department, designation, manager, location, status, joining date, last updated, organization | Done | `employees` table (docs/07); `test_create_employee` |
| B2 | Create, retrieve, update, archive | Done | `test_employees_api.py`; browser workforce test |
| B3 | List, search, filter, paginate | Done | `test_search`, `test_filters`, `test_pagination_is_stable_and_complete`; v2 cursor pagination `test_api_v2.py` |
| B4 | Lifecycle events: created, updated, department_changed, manager_changed, terminated | Done | `test_lifecycle_events.py` |
| B5 | Validation of every request | Done | `test_create_rejects_invalid_input`, `test_create_requires_mandatory_fields` |
| B6 | Constraints and indexes | Done | `test_employee_models.py`; composite same-organization foreign keys (ADR-0006) |
| B7 | No unnecessary exposure of sensitive data | Done | IDs only in logs and events; `test_events_are_listed_without_personal_data` |
| B8 | Departments and reporting lines (cycle prevention) | Done | `test_departments_api.py`, `test_manager_cycles_are_rejected`, `test_simultaneous_manager_changes_cannot_form_a_cycle` |
| B9 | Concurrent edits do not overwrite each other | Done | `test_optimistic_concurrency.py` (412 with `If-Match`) |

## C. Connector framework

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| C1 | Slack, Google Workspace, payroll connectors | Done (simulated) | `test_connector_adapters.py` (each runs the same lifecycle against its mock) |
| C2 | Common interface: create, update, deactivate, get user, test connection | Done | `connectors/base.py`; adapter tests |
| C3 | Registration, configuration, versioning | Done | `test_connector_core.py` (registry, major-version refusal); `test_catalog_lists_every_connector_type` |
| C4 | Credential storage, encrypted, never returned | Done | `test_create_connector_encrypts_credentials_and_never_returns_them`, `test_encryption.py` |
| C5 | Connection status and health checks | Done | `test_successful_connection_test`, `test_failed_connection_test_records_the_normalized_error` |
| C6 | Error normalization, rate limits, timeouts | Done | adapter tests for 401, 404, 409, 503, 429 + `Retry-After`, timeouts |
| C7 | New connectors without changing the engine | Done | adapter pattern (ADR-0008); docs/10 "Adding a connector" |
| C8 | Realistic mock services with failure simulation | Done | `mock-services/`, fault API |
| C9 | Real versus simulated clearly documented | Done | `simulated: true` in the catalog, "Simulated" badge in the UI, docs/10 section 1 |

## D. Workflows

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| D1 | Create, edit, activate, deactivate | Done | `test_workflows_api.py`; browser integrations test |
| D2 | Ordered steps, sequential execution | Done | `test_onboarding_creates_accounts_in_every_application`, `test_a_failed_step_fails_the_execution_and_skips_the_rest` |
| D3 | Execution history with per-step status and failures | Done | `test_execution_history_shows_per_step_status`, `test_event_detail_includes_executions_and_steps` |
| D4 | Onboarding and termination examples | Done | `test_offboarding_deactivates_the_accounts`; case studies 1 and 3 |
| D5 | Configurable engine, not hardcoded | Done | workflows stored as data; docs/11 |

## E. Event processing

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| E1 | Persistent events with IDs, status, timestamps, failure information | Done | `integration_events`; `test_event_outbox.py`, `test_events_api.py` |
| E2 | Background processing with Redis and workers | Done | `test_celery_worker.py` |
| E3 | Statuses (brief: pending, processing, completed, failed, retrying, dead letter) | Done, without a separate `failed` | `IntegrationEventStatus` has pending, processing, retrying, completed, dead_letter: a permanent failure goes straight to `dead_letter`, where it is visible and replayable (docs/02 section 6) |
| E4 | Transactional outbox | Done | `test_employee_change_and_its_events_share_one_transaction`, `test_outbox_relay.py` |
| E5 | At-least-once delivery with idempotent consumers | Done | `test_duplicate_delivery_is_skipped_and_creates_nothing_twice` |

## F. Reliability

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| F1 | Exponential backoff with jitter, configurable limit | Done | `test_retries.py` |
| F2 | Idempotency (event IDs, operation IDs, keys) | Done | `test_idempotency.py`; docs/13 |
| F3 | Dead-letter queue with inspection and authorized replay | Done | `test_dead_letters.py`; browser reliability test |
| F4 | HTTP 429 and `Retry-After` | Done | `test_rate_limit_waits_at_least_retry_after` |
| F5 | Connection, read and operation timeouts | Done | `test_timeouts_are_retried`, `test_one_operation_cannot_exceed_its_deadline_across_requests` |
| F6 | Circuit breaker (closed, open, half-open) | Done | `test_circuit_breaker.py` |
| F7 | Failure classification; permanent failures not retried | Done | `test_permanent_failures_are_dead_lettered_at_once` |

## G. Data integrity

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| G1 | Field-level, configurable source of truth | Done | `data_source_policies`; `test_every_field_has_a_default_policy_and_hr_is_the_default_authority`, `test_an_identity_provider_can_be_authoritative_for_account_status` |
| G2 | Conflict detection with severity and history | Done | `test_a_difference_is_recorded_not_overwritten`, `test_a_terminated_person_with_an_active_account_is_critical` |
| G3 | Resolution policies and manual resolution | Done | `test_conflicts.py` (override and note rules, auto mode); browser governance test |
| G4 | Conflict audit trail | Done | `conflict.detected` / `.resolved` audit entries |

## H. Audit logging

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| H1 | Employee, connector, workflow, failure, retry, conflict and permission actions recorded | Done | `test_audit.py` |
| H2 | Organization, actor, action, resource, time, metadata, outcome | Done | `audit_logs` (docs/07) |
| H3 | No secrets or personal values | Done | `test_employee_lifecycle_is_audited_without_personal_values`, `test_connector_changes_are_audited_without_secrets` |
| H4 | Append-only | Done | `test_entries_cannot_be_updated`, `test_entries_cannot_be_deleted_except_by_an_explicit_retention_transaction` |

## I. Monitoring and observability

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| I1 | Dashboard: employees, integrations, successes, failures, pending, retries, dead letters, history, connector health, recent activity | Done | Angular dashboard from `GET .../summary` and the audit log; `test_summary_counts_equal_the_list_endpoints_totals` |
| I2 | Structured logs, request, correlation and event IDs | Done | `test_response_carries_generated_request_id`; docs/18 |
| I3 | Health and readiness endpoints | Done | `test_health.py` |
| I4 | Processing durations, worker and relay health | Done | `test_monitoring.py`; docs/18 |
| I5 | Investigation guide for a failed synchronization | Done | docs/18 section 5, docs/21 |

## J. Developer API

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| J1 | Consistent envelopes, validation, pagination, filtering, error codes | Done | docs/08; `test_unknown_route_uses_error_envelope` |
| J2 | Authentication and authorization on every endpoint | Done | `test_requires_authentication` and per-module tests |
| J3 | Rate limiting where appropriate | Done | sign-in and registration limits; per-connector limits |
| J4 | `/api/v1` namespace and a `/api/v2` demonstration | Done | `test_api_v2.py`; docs/08 section 14; ADR-0021 |
| J5 | OpenAPI documentation | Done | `/docs`; snapshot checked by `npm run api:check` |

## K. Web application

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| K1 | The 16 pages of the brief (login, dashboard, employees, details, integrations, connector configuration, workflow builder and history, events, failed synchronizations, dead letters, conflicts, audit log, API documentation, users and roles, settings) | Done | docs/PHASE_8_FRONTEND_COMPONENTS.md; browser suite. API documentation: the "Developer API" card in Settings opens the interactive reference (`/docs`, added in Phase 10, where this gap was found) |
| K2 | Loading, empty and error states; validation; confirmations; notifications; search, filters, pagination; responsive | Done | shared components; browser phone-layout test |
| K3 | No decorative controls; real backend data only | Done | docs/PHASE_8_FRONTEND_REPORT.md section 2 |
