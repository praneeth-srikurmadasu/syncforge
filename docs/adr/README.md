# Architecture decision records

Each record states the context, the problem, the alternatives considered, the decision,
the trade-offs and the consequences. A decision gets a record when it is hard to reverse,
affects several modules, or rejects a reasonable alternative. Records are not edited to
change a decision; a later record supersedes it.

The records were written while the project was built in ten phases. "Phase N" in a
record refers to that build order and dates the decision.

| ADR | Decision | The trade-off in one line |
|---|---|---|
| [0001](0001-modular-monolith-with-fastapi.md) | Modular monolith with FastAPI; workers from the same codebase | One deployable and one database transaction boundary, instead of independent service scaling |
| [0002](0002-postgresql-as-system-of-record.md) | PostgreSQL as the system of record | Strong constraints and transactions; Redis holds nothing that cannot be rebuilt |
| [0003](0003-synchronous-sqlalchemy.md) | Synchronous SQLAlchemy 2 with Alembic | Simpler, well-understood code and tests; concurrency comes from processes, not an event loop |
| [0004](0004-jwt-access-tokens-with-revocation-denylist.md) | Short-lived JWTs with a revocation list | Stateless checks plus real logout; one lookup per request |
| [0005](0005-organization-level-data-isolation.md) | Isolation by `organization_id`, 404 for non-members | Simple to reason about and test; relies on every query being scoped |
| [0006](0006-composite-foreign-keys-for-tenant-integrity.md) | Composite same-organization foreign keys | The database refuses cross-tenant references, at the cost of wider keys |
| [0007](0007-advisory-lock-for-reporting-line-changes.md) | Advisory lock for manager changes | Prevents reporting-line cycles under concurrency; serializes those changes per organization |
| [0008](0008-connector-adapter-pattern.md) | Adapter interface with a registry | New applications without engine changes; a common error model to maintain |
| [0009](0009-encrypting-connector-credentials.md) | Fernet encryption of credentials at rest, write-only API | Credentials useless without the key; key management becomes an operator duty |
| [0010](0010-redis-and-celery-for-background-work.md) | Redis as broker, Celery workers | Mature tooling; Windows needs the solo pool |
| [0011](0011-asynchronous-event-processing.md) | Asynchronous processing, at-least-once with idempotent consumers | Fast API responses and resilience; eventual consistency and duplicate handling |
| [0012](0012-transactional-outbox.md) | Transactional outbox and relay | No lost or phantom events; a relay process and slight delay |
| [0013](0013-retries-with-exponential-backoff-and-jitter.md) | Exponential backoff with jitter, bounded attempts, `Retry-After` | Gentle on failing services; a long outage ends in the dead-letter queue |
| [0014](0014-dead-letter-queue-and-replay.md) | Dead-letter queue in PostgreSQL with partial, authorized replay | Failures are visible and fixable by a person; replays need a decision |
| [0015](0015-idempotency-keys.md) | Idempotency keys on external creates and on `POST /employees` | Safe retries; real SaaS APIs may not honour the header (documented) |
| [0016](0016-shared-circuit-breaker-and-rate-limits.md) | Breaker and rate limits per connector, shared in PostgreSQL | Correct across many workers; a write per external call |
| [0017](0017-append-only-audit-log.md) | Append-only audit log in the same transaction | No action without its record; a table that only grows |
| [0018](0018-optimistic-concurrency-with-etags.md) | Optimistic concurrency with ETag / `If-Match` | No lost updates without locks; clients must handle 412 |
| [0019](0019-field-level-source-of-truth-and-reconciliation.md) | Field-level source-of-truth policies; conflicts recorded, resolved explicitly | No silent overwrites; conflicts need attention |
| [0020](0020-angular-frontend-signals-and-server-state.md) | Angular with signals and server state, generated API types | Little code and contract safety; no offline or real-time state |
| [0021](0021-path-versioning-and-keyset-pagination.md) | Path versions; v2 employee list with keyset pagination | Stable pages and fast deep pages; no totals or page jumps in v2 |

## Smaller decisions

| Decision | Why |
|---|---|
| No separate `failed` event status | A permanent failure goes to `dead_letter`, where it is visible and replayable |
| Workers act on current state, not the event's snapshot | A terminated person's queued "create account" step is skipped instead of creating access |
| Sign-in limits in PostgreSQL, not Redis | Signing in must not depend on the broker |
| Sign-in history in its own table | Sign-ins are not organization-scoped, which keeps the audit log's tenant model intact |
| `/ready` checks only the database | A worker outage must not take the API offline |
| Polling instead of WebSockets in the UI | No push channel to operate; screens poll only while visible |
| One backend image for the API, worker, relay and migrations | One build; roles differ only in their command |
| nginx serves the web app and forwards API paths | One origin: no CORS, and the API port is not published |
| Simulated applications, marked as simulated everywhere | Realistic failure testing without paid accounts, and without pretending |
| Index on the full sort key, decided by measurement | Measured sorts before, plain index scans after ([performance](../performance.md)) |
