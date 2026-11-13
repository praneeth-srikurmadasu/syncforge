# 22 - Interview preparation

How to explain SyncForge confidently. Part 1 is a timed walkthrough for a 10-15 minute
presentation. Part 2 covers 21 topics, each with a simple explanation, why SyncForge
needs it, where it is in the code, an example, alternatives, trade-offs, likely questions
and strong answers. Part 3 has general questions. Every number quoted here was measured
or counted in this repository (docs/19, docs/16); quote them with their conditions.

---

## Part 1 - Project walkthrough (10-15 minutes)

| Minute | Say | Show |
|---|---|---|
| 0-1 | **Problem.** Employee data lives in many applications; joiners wait for accounts and leavers keep access. SyncForge turns HR changes into reliably processed synchronization events. | README diagram |
| 1-3 | **Architecture.** A modular monolith: FastAPI API, PostgreSQL as the system of record, a transactional outbox, a relay that publishes to Redis, Celery workers that run configurable workflows through connector adapters. Angular front end. Why a monolith: one transaction boundary, one deployable, independent scaling of workers is still possible. | docs/05 diagram, ADR-0001 |
| 3-5 | **Live: onboarding.** Create an employee; show the event completing with three steps, each attempt with its HTTP status and the linked accounts. | UI: Employees -> Events -> event page |
| 5-7 | **Reliability.** Inject 503s into the payroll mock; show retries with backoff (2, 4, 8, 16 s), the dead-letter entry with the preserved error, then replay: only the failed step reruns. Mention the circuit breaker and `Retry-After`. | UI: Reliability, Dead letters |
| 7-8 | **Correctness under duplicates.** At-least-once delivery; atomic claim with a lease; one execution per event and workflow; idempotency keys on external creates. "We never claim exactly-once; we make processing idempotent." | docs/13, case study 6 |
| 8-9 | **Data integrity.** Reconcile payroll; a department difference becomes a conflict, not an overwrite; field-level source-of-truth policy; override needs a note. Optimistic concurrency with `If-Match` against lost updates. | UI: Conflicts |
| 9-10 | **Security and multi-tenancy.** Organization isolation (404 for non-members, composite foreign keys), RBAC with four roles, Argon2id, JWT with revocation, sign-in rate limits, encrypted credentials, append-only audit log and sign-in history. | docs/15 section 11 |
| 10-11 | **Observability and performance.** Request and correlation IDs, heartbeats and system status, processing percentiles; measured 9-17 ms p50 per request and about 10 events/s per worker on a 2-CPU machine, 1.7x with a second worker; an index changed because of a measurement. | docs/18, docs/19 |
| 11-12 | **Quality and delivery.** 579 backend tests on real PostgreSQL, 60 unit and 13 browser tests with accessibility checks, Docker Compose for the whole stack, CI running the browser tests against the containers. | docs/16, CI |
| 12-14 | **Trade-offs and what's next.** Eventual consistency; mocks not real tenants; sequential steps; what I would build next (real connectors with find-before-create, MFA, retention, parallel steps). | docs/23 |
| 14-15 | Questions. | |

**One-sentence summary:** "SyncForge is an event-driven workforce synchronization
platform where every HR change is committed together with its event, processed at least
once by idempotent workers through pluggable connectors, retried with backoff and a
circuit breaker, parked in a dead-letter queue for replay when it cannot succeed, and
audited end to end."

---

## Part 2 - Topics

Each topic: **What** (simple explanation) · **Why here** · **In the code** · **Example**
· **Alternatives** · **Trade-offs** · **Questions** with **answers**.

### 1. High-level architecture

- **What:** the major parts and how they talk: API, database, outbox relay, broker,
  workers, connectors, web app.
- **Why here:** HR changes must be accepted fast and never lost, while external
  applications are slow and unreliable; so accepting a change and acting on it are split.
- **In the code:** `backend/app/api` (HTTP), `services` (rules and transactions),
  `events/outbox.py` + `events/relay.py`, `workers/` (Celery), `workflows/engine.py`,
  `connectors/` (adapters), `frontend/`.
- **Example:** a hire is one transaction in the API; the relay and worker do the rest.
- **Alternatives:** microservices; synchronous calls from the API; a workflow engine
  product (Temporal).
- **Trade-offs:** a monolith is simpler to operate and keeps one transaction boundary;
  scaling is per process type rather than per service.
- **Q:** Why not microservices? **A:** No team or scaling boundary justified them; the
  hard parts here are transactional consistency between an HR change and its event, which
  a single database gives for free. Workers already scale independently, and modules are
  separated by package so a split later would follow existing seams.

### 2. Database design

- **What:** tables, keys, constraints and indexes that make invalid states impossible.
- **Why here:** multi-tenant HR data, lifecycle rules and processing state must stay
  consistent under concurrency.
- **In the code:** `backend/app/models`, migrations 0001-0016, docs/07 with the ER diagram.
- **Example:** `employees` has composite foreign keys `(organization_id, manager_id)` so a
  manager from another organization is rejected by the database; check constraints make
  `terminated` require a termination date.
- **Alternatives:** validation only in code; a document store.
- **Trade-offs:** constraints cost wider keys and careful migrations; they catch bugs the
  code missed.
- **Q:** How do you index a multi-tenant table? **A:** Every index leads with
  `organization_id`, because every query filters by it. I widened the employee name index
  to the full sort key `(organization_id, last_name, first_name, id)` after `EXPLAIN
  ANALYZE` showed a sort step; pages then became plain index scans (0.115 -> 0.032 ms).

### 3. API design

- **What:** resource-oriented REST with consistent envelopes, errors and paging.
- **Why here:** the UI, scripts and future integrations all depend on a stable contract.
- **In the code:** `app/api/v1`, `app/api/v2`, `app/core/errors.py` (one error envelope
  with `code`, `message`, `details`, `request_id`), docs/08.
- **Example:** `PATCH /employees/{id}` with `If-Match` returns `412 version_conflict` on a
  stale version; `POST /employees` honours `Idempotency-Key`.
- **Alternatives:** GraphQL; RPC-style endpoints.
- **Trade-offs:** REST is predictable and cacheable; some screens need several calls
  (solved where it mattered with `GET .../summary`: 48 -> 33 requests per dashboard load).
- **Q:** How do you evolve an API? **A:** Additive changes stay in v1; breaking ones get a
  new path version containing only the changed endpoints. v2's employee list changed the
  paging model to keyset cursors, so it is `/api/v2`; v1 is unchanged and tested to stay so.

### 4. Event-driven architecture

- **What:** components react to recorded events instead of calling each other directly.
- **Why here:** an HR change triggers work in several applications, any of which may fail.
- **In the code:** `events/lifecycle.py` (pure function that derives events from a
  before/after comparison), `integration_events`, `workflows/engine.py`.
- **Example:** changing department and designation in one request yields
  `employee.department_changed` and `employee.updated`.
- **Alternatives:** synchronous orchestration in the request; database triggers.
- **Trade-offs:** resilience and decoupling, at the cost of eventual consistency and more
  moving parts to observe.
- **Q:** What is in an event? **A:** IDs and changed field names, not personal values;
  the worker reads the current employee record when it runs, so a stale event cannot
  create access for someone already terminated.

### 5. Message queues

- **What:** a broker that holds messages until a consumer takes them.
- **Why here:** to hand work from the relay to any number of workers.
- **In the code:** Redis as Celery's broker (`workers/celery_app.py`); the message is only
  "process event X".
- **Example:** three workers share one queue; each event goes to one of them.
- **Alternatives:** RabbitMQ, Kafka, PostgreSQL itself as a queue (`SKIP LOCKED`).
- **Trade-offs:** Redis is simple and fast but not a durable log; that is acceptable
  because PostgreSQL is the source of truth and the relay re-publishes.
- **Q:** What if Redis loses messages? **A:** Nothing is lost: events stay pending or
  past their lease in PostgreSQL and the relay publishes them again. Redis runs without
  persistence on purpose.

### 6. At-least-once delivery

- **What:** a message may be delivered more than once, never zero times.
- **Why here:** retries and recovery after crashes inevitably cause duplicates.
- **In the code:** relay re-dispatch of due retries and expired leases; worker `_claim`.
- **Example:** a worker dies after calling Slack but before committing; the event is
  delivered again.
- **Alternatives:** at-most-once (lose work); "exactly once" (not possible end to end
  with external APIs).
- **Trade-offs:** requires idempotent consumers everywhere.
- **Q:** Can you guarantee exactly once? **A:** Not across a broker and third-party APIs.
  I guarantee at-least-once delivery and make every effect idempotent: atomic claim, one
  execution per event and workflow, skipped succeeded jobs, idempotency keys outward.

### 7. Idempotency

- **What:** doing an operation twice has the same effect as doing it once.
- **Why here:** duplicates from section 6 and user double-clicks.
- **In the code:** `reliability/idempotency.py` (incoming `Idempotency-Key` on
  `POST /employees`, stored with the response), `syncforge-job-<id>` keys on external
  creates (`workflows/engine.py`), unique constraints on executions and account links.
- **Example:** a timed-out payroll create is retried with the same key; the mock returns
  the account it already created.
- **Alternatives:** natural keys only; "check then create".
- **Trade-offs:** stored keys need expiry (`purge-expired`); real SaaS APIs may ignore the
  header, so a crash there surfaces as a visible conflict rather than a duplicate.
- **Q:** How do you detect a duplicate request? **A:** The client sends a key; the first
  request stores it atomically with a hash of the body and, when done, the response.
  A repeat returns the stored response with `Idempotent-Replayed: true`; the same key with a
  different body is `422 idempotency_key_reused`; a concurrent identical request waits for
  and gets the winner's response.

### 8. Transactional outbox

- **What:** write the event to an outbox table in the same transaction as the change;
  publish it afterwards.
- **Why here:** to avoid "saved but never published" and "published but rolled back".
- **In the code:** `events/outbox.py`, `events/relay.py` (`FOR UPDATE SKIP LOCKED`),
  ADR-0012.
- **Example:** with Redis stopped, hires still succeed; when it returns, the relay
  publishes them (Phase 5: three waiting events published in order).
- **Alternatives:** publish then commit; two-phase commit; change data capture
  (Debezium).
- **Trade-offs:** an extra process and a small delay; very reliable and simple to test.
- **Q:** Why not publish directly from the API? **A:** The database commit and the broker
  publish are two systems; any crash between them leaves them inconsistent. The outbox
  turns it into one atomic database write plus a retriable publish.

### 9. Exponential backoff with jitter

- **What:** wait longer after each failure, with randomness so clients do not retry in
  lockstep.
- **Why here:** external outages and rate limits.
- **In the code:** `reliability/retry.py`: `min(300, 2 x 2^(n-1))` s, +-20 % jitter, at
  least `Retry-After`, 5 attempts.
- **Example:** 503s on payroll: attempts after about 2, 4, 8 and 16 s, then dead letter.
- **Alternatives:** fixed delay; immediate retries; unbounded retries.
- **Trade-offs:** gentle on the failing service; a long outage ends in the dead-letter
  queue and needs a replay.
- **Q:** Why jitter? **A:** Without it, every job that failed at the same moment retries
  at the same moment and hits a recovering service together (thundering herd).

### 10. Circuit breakers

- **What:** stop calling a service that keeps failing; try again after a pause.
- **Why here:** an application outage should not burn every job's retry budget.
- **In the code:** `reliability/circuit_breaker.py`, state in `connector_circuits`
  shared by all workers; 5 consecutive outage failures (server, timeout, network) open
  it for 60 s, then one half-open trial.
- **Example:** Google down during three hires: open after 5 requests, no calls while open,
  one trial after 60 s closed it (Phase 6 live run).
- **Alternatives:** per-process breakers; no breaker.
- **Trade-offs:** shared state costs a database write per call; per-process state would
  let each worker hammer the service separately.
- **Q:** Do authentication errors open the circuit? **A:** No. Only outage categories
  count; a 401 is a configuration problem and goes straight to the dead-letter queue.

### 11. Dead-letter queues

- **What:** a holding place for work that cannot succeed automatically.
- **Why here:** permanent failures and exhausted retries need a person.
- **In the code:** `reliability/dead_letter.py`, `services/dead_letters.py`,
  `dead_letter_events` with the copied error and reason (`retries_exhausted` or
  `non_retryable`).
- **Example:** replay reruns only the failed steps with a fresh retry budget; a second
  replay is `409 already_replayed`.
- **Alternatives:** a broker-level DLQ; endless retries.
- **Trade-offs:** stored in PostgreSQL so it is queryable, permissioned and audited;
  replay is manual by design.
- **Q:** What if two admins press Replay together? **A:** The entry row is locked; exactly
  one replay happens (`test_simultaneous_replays_of_one_entry_replay_it_once`).

### 12. Rate limiting

- **What:** limit how often something can happen.
- **Why here:** two directions: protect SyncForge's sign-in from guessing, and stay under
  each external application's limits.
- **In the code:** `security/rate_limit.py` (per-IP and per-account sign-in limits,
  registration per IP, 429 with `Retry-After`), `reliability/rate_limit.py`
  (`rate_limit_per_minute` per connector).
- **Example:** after 10 failed sign-ins for one email in 15 minutes, even the right
  password gets 429 until the window ends.
- **Alternatives:** token bucket or sliding window; Redis counters; an API gateway.
- **Trade-offs:** fixed windows in PostgreSQL are simple and shared but allow up to twice
  a limit across a boundary; the per-account limit can delay a known user's sign-in.
- **Q:** Why PostgreSQL rather than Redis for sign-in limits? **A:** Signing in must not
  depend on the broker; every API process shares the counters; the cost is one small
  upsert per attempt, and subjects are stored hashed.

### 13. OAuth 2.0

- **What:** a client obtains a short-lived access token from an authorization server
  instead of using a password.
- **Why here:** Google Workspace's Directory API uses OAuth.
- **In the code:** `connectors/google_workspace.py`: token request with the client
  credentials, process-local cache, refresh before expiry, and one retry with a new token
  on 401. The local mock implements the `client_credentials` grant.
- **Example:** the mock expires every token; the next call fetches a new one and succeeds.
- **Alternatives:** API keys (payroll), static tokens (Slack SCIM).
- **Trade-offs:** honest limit: real Google needs a service account with domain-wide
  delegation and the JWT-bearer grant; the browser authorization-code flow is not built.
- **Q:** What would change for real Google? **A:** The token request becomes a signed JWT
  assertion for a service account impersonating an admin; the rest of the adapter
  (caching, refresh, error mapping) stays.

### 14. Database transactions

- **What:** a group of changes that commit or roll back together.
- **Why here:** an employee change, its events, its outbox rows and its audit entry must
  be all-or-nothing.
- **In the code:** services own the transaction; `audit.record` and `record_events` add
  rows to the same session.
- **Example:** a failed change leaves no audit entry (`test_a_failed_change_leaves_no_entry`).
- **Alternatives:** separate writes with compensation.
- **Trade-offs:** keeping external calls outside transactions (workers commit around
  each call) avoids holding locks while waiting on the network.
- **Q:** Do you call external APIs inside a transaction? **A:** No. A worker claims the
  event and commits, calls the API, then records the result in a new transaction; leases
  and idempotency keys cover a crash in between.

### 15. Optimistic concurrency

- **What:** detect conflicting writes at save time instead of locking in advance.
- **Why here:** two admins editing the same employee in different tabs.
- **In the code:** `employees.version`, `ETag`, `If-Match`, `412 version_conflict`
  (ADR-0018); the UI offers "Load latest".
- **Example:** two saves from version 3: the first gets 200, the second 412.
- **Alternatives:** pessimistic locks; last write wins.
- **Trade-offs:** no locks held during editing; clients must handle 412.
- **Q:** Where do you still use locks? **A:** Where an invariant spans rows: an advisory
  lock serializes manager changes so two concurrent edits cannot form a reporting cycle,
  and row locks protect "at least one admin" and replays.

### 16. Data consistency

- **What:** keeping data correct across SyncForge and external applications.
- **Why here:** applications drift (manual edits, partial failures).
- **In the code:** reconciliation and conflicts (`services/conflicts.py`), field-level
  policies (`integrity/fields.py`, `data_source_policies`).
- **Example:** payroll says Finance, SyncForge says Engineering: a conflict is recorded;
  keeping SyncForge's value pushes it to payroll.
- **Alternatives:** last write wins; SyncForge always overwrites.
- **Trade-offs:** explicit conflicts need attention but never lose data silently; there is
  no universal source of truth, it is configured per field.
- **Q:** What consistency do you guarantee? **A:** Inside SyncForge, strong (transactions,
  constraints). Towards external applications, eventual: changes converge through retries,
  and reconciliation detects what drifted anyway.

### 17. Multi-tenancy

- **What:** many organizations share one deployment without seeing each other's data.
- **Why here:** SaaS-style platform.
- **In the code:** `organization_id` on every table and query, `require_org_permission`,
  404 for non-members, composite same-organization foreign keys (ADR-0005, ADR-0006).
- **Example:** an admin of organization A requesting B's employee gets 404, not 403.
- **Alternatives:** schema per tenant; database per tenant; PostgreSQL row-level security.
- **Trade-offs:** shared schema is simplest to operate and migrate; it depends on every
  query being scoped, which tests enforce endpoint by endpoint.
- **Q:** Why 404 instead of 403? **A:** 403 would confirm the organization exists; 404
  reveals nothing to outsiders.

### 18. Horizontal scaling

- **What:** adding instances instead of bigger machines.
- **Why here:** event throughput and API traffic grow independently.
- **In the code:** stateless API (JWT), workers coordinated through PostgreSQL claims, a
  relay safe to duplicate (`SKIP LOCKED`).
- **Example:** measured 9.5 -> 16.3 events/s from one to two workers on a 2-CPU machine.
- **Alternatives:** vertical scaling only.
- **Trade-offs:** more connections to PostgreSQL (pool per process); per-employee
  ordering across workers is not guaranteed (safe because steps read current state).
- **Q:** What is the bottleneck? **A:** At this scale, per-request work in the API and the
  external call latency in workers; the database queries are well under a millisecond
  except search and the summary, which read a whole organization (docs/19 section 5).

### 19. Worker concurrency

- **What:** several workers processing at once without stepping on each other.
- **Why here:** throughput and resilience.
- **In the code:** `_claim` is a conditional `UPDATE` with a lease (`locked_until`, 300 s);
  succeeded jobs are skipped on resume.
- **Example:** a bug found in a live run: a worker could skip a due retry while the relay
  still held the row under READ COMMITTED; fixed by making due retries claimable, with a
  regression test.
- **Alternatives:** `SELECT ... FOR UPDATE` for the whole processing; a single worker.
- **Trade-offs:** leases recover crashed workers without holding locks; lease length
  balances recovery time against stealing from slow but alive workers.
- **Q:** How do you prevent two workers processing one event? **A:** The claim only
  succeeds if the event is pending, a due retry, or past its lease, and atomically sets a
  new lease; the loser updates zero rows and skips.

### 20. Failure recovery

- **What:** returning to a correct state after crashes and outages.
- **Why here:** workers, brokers and external applications all fail.
- **In the code:** outbox (no lost events), leases and relay re-dispatch (crashed
  workers), retries and breaker (outages), dead letters and replay (permanent failures),
  reconciliation (drift).
- **Example:** worker killed with `kill -9` mid-call; the next worker completed the event
  on attempt 2 with no duplicate (Phase 5 live run).
- **Alternatives:** manual repair scripts.
- **Trade-offs:** each mechanism adds state to understand, so each is observable in the
  UI and API.
- **Q:** Walk me through recovery from a worker crash. **A:** Case study 8.

### 21. Monitoring and observability

- **What:** being able to tell what the system is doing and why something failed.
- **Why here:** asynchronous work fails away from the user who caused it.
- **In the code:** JSON logs with request and correlation IDs (`core/logging.py`),
  `/health`, `/ready`, heartbeats and `GET /system/status`, `GET .../summary` with p50/p95
  processing times, attempt history per event (docs/18).
- **Example:** with the worker stopped for 70 s, system status reported "No worker has
  reported in the last 60 seconds".
- **Alternatives:** Prometheus and OpenTelemetry (future).
- **Trade-offs:** no metrics stack to run; JSON endpoints must be polled.
- **Q:** Why doesn't `/ready` check the workers? **A:** Readiness decides whether the API
  should get traffic. A worker outage should not stop people recording changes, which wait
  safely in the outbox; it is a separate, alertable signal.

---

## Part 3 - General questions

**What was the hardest bug?** The READ COMMITTED race in Phase 6: the relay published a
due retry while still holding the row, so a fast worker saw `retrying` and skipped it.
Found in a live run, explained by how PostgreSQL re-evaluates `UPDATE ... WHERE` under
READ COMMITTED, fixed by making due retries claimable, and pinned with a test that fails
without the fix.

**What would you do differently?** Start the browser tests and accessibility checks
earlier (they found real contrast and layout defects only in Phase 8); add a dashboard
summary endpoint from the start instead of composing totals from list calls; pin a
container check earlier, because it found a missing runtime dependency (`packaging`) that
the development environment hid.

**How do you know it works?** 579 backend tests against real PostgreSQL including
concurrency races, 60 unit and 13 browser tests, CI with the Docker stack, repeated and
random-order runs, and a clean-clone run (final engineering report, section 11).

**What is simulated?** All three external applications are local mocks with realistic
behaviour and fault injection; marked "Simulated" in the API and UI.

**How would you scale to 10,000 organizations?** Keep the shared schema with
`organization_id`-leading indexes, add a pooler, more API instances and workers,
retention jobs, trigram search, and eventually partition event tables by time; measure at
the target size before changing anything (docs/19).

**How do you handle secrets?** Environment variables from a secrets manager in
production; Fernet-encrypted connector credentials that the API never returns; nothing in
logs or audit records; the application refuses to start in production with placeholders.
