# 04 - Non-functional requirements

Quality requirements, the target chosen for each, and the evidence. Targets are what the
design commits to at the scale SyncForge is built for (section 5 of docs/02: human-rate
workforce changes, tenants sharing one deployment).

| ID | Quality | Requirement | How it is met | Evidence |
|---|---|---|---|---|
| N1 | Reliability | No employee change is lost, even if the broker or a worker is down | Transactional outbox: the change and its event commit together; the relay re-publishes; leases recover crashed workers | `test_employee_change_and_its_events_share_one_transaction`, `test_relay_recovery_hands_a_crashed_workers_event_to_the_next_worker`; case studies 4 and 8 |
| N2 | Reliability | Duplicate deliveries never create duplicate accounts | At-least-once delivery, atomic claim, one execution per (event, workflow), idempotency keys on external creates | `test_duplicate_delivery_is_skipped_and_creates_nothing_twice`, `test_a_timed_out_create_is_retried_safely` |
| N3 | Reliability | Failures are retried with bounds, then surfaced | Exponential backoff with jitter, 5 attempts by default, circuit breaker, dead-letter queue | `test_retries.py`, `test_circuit_breaker.py`, `test_dead_letters.py` |
| N4 | Consistency | Concurrent edits never silently overwrite each other | Optimistic concurrency (`version`, `If-Match`, 412); row locks and advisory locks where invariants span rows | `test_optimistic_concurrency.py`, `test_concurrency.py` |
| N5 | Consistency | Differences with external applications are recorded, not overwritten | Field-level source-of-truth policies, conflicts with resolution rules | `test_conflicts.py` |
| N6 | Security | Tenants cannot see or change each other's data | `organization_id` on every query, 404 for non-members, composite foreign keys | `test_cross_organization_access_is_404_everywhere`; ADR-0005, ADR-0006 |
| N7 | Security | Credentials and secrets are protected | Argon2id, Fernet-encrypted connector credentials, no secrets in logs, audit or responses; production refuses placeholder secrets | docs/15 section 11 (20 controls with tests) |
| N8 | Security | Abuse of sign-in and request size is limited | Per-IP and per-account limits, common-password refusal, 1 MiB body limit | `test_security_hardening.py` |
| N9 | Auditability | Every important action is traceable and tamper-resistant | Append-only audit log and security events, written in the same transaction as the change | `test_audit.py`, `test_security_events.py` |
| N10 | Performance | Typical API requests well under 100 ms at the target scale | Measured 8-17 ms p50 (1,000-10,000 employees, 2-CPU machine); keyset pagination and the full sort index for deep pages | docs/19 section 3 |
| N11 | Throughput | Background processing scales by adding workers | Stateless workers, atomic claims, shared rate-limit and breaker state | Measured 9.5 -> 16.3 events/s from 1 to 2 workers (docs/19 section 3.2) |
| N12 | Availability | A worker or broker outage does not take the API offline | `/ready` depends only on PostgreSQL; events wait in the outbox | `test_ready_does_not_depend_on_background_processes`; docs/18 section 3 |
| N13 | Observability | A failed synchronization can be traced from request to external call | Request and correlation IDs in every log line, attempt history, system status | docs/18 section 5; `test_monitoring.py` |
| N14 | Maintainability | New connectors without changing the engine; layered code; typed | Adapter registry; routers -> services -> repositories; type hints, ruff, strict TypeScript | ADR-0008; lint in CI |
| N15 | Testability | Behaviour is verified automatically, on every push | 579 backend, 60 frontend unit, 13 browser tests; CI with PostgreSQL, Redis and the Docker stack | docs/16; `.github/workflows/ci.yml` |
| N16 | Accessibility | WCAG 2 AA for the web application | Contrast tokens, landmarks, labels, keyboard focus; axe on 14 pages in both themes | browser `quality.spec.ts` |
| N17 | Usability | Clear states and messages; works on phones | Loading, empty and error states with request IDs; 390 px layouts | browser phone-layout test |
| N18 | Portability | Runs the same on Windows development machines, Linux CI and containers | PowerShell instructions, Docker images, CI on Ubuntu | README; CI |
| N19 | Data protection | Minimal personal data outside the employee record | IDs only in logs and events; field names, not values, in audit records; hashed rate-limit subjects | `test_personal_values_never_reach_the_audit_log`, `test_counters_store_hashes_not_addresses_or_emails` |

## Not targeted

- High availability of a single deployment (redundant instances, failover) is a
  deployment concern, described in docs/17 but not built.
- Formal load limits under concurrent traffic were not measured (docs/19 section 7).
- Data retention and deletion schedules (GDPR-style erasure) are future improvements
  (docs/23).
