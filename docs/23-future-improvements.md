# 23 - Future improvements

What would come next, collected from the known limitations recorded during the project
(final engineering report section 14, docs/15 section 10, docs/19 section 5). Ordered by
value within each group. None of these is implemented.

## 1. Real integrations

| Improvement | Why | Notes |
|---|---|---|
| Real Slack and Google Workspace connectors against real tenants | The current adapters are verified against mocks only | Google needs the JWT-bearer (service account, domain-wide delegation) grant; Slack SCIM needs an Enterprise Grid / Business+ token (docs/10 section 1) |
| "Find before create": adopt an existing account by email | Real SCIM and Directory APIs do not honour idempotency keys, so a crash between create and link produces a conflict instead of a duplicate (visible, but manual) | docs/13 section 3 |
| OAuth authorization-code flow ("Connect with Google") | Admins paste credentials today | Needs redirect handling and token storage per connector |
| Webhooks or polling from external applications | Changes made directly in Slack or Google are found only by reconciliation | Turn external changes into events with the same pipeline |
| Scheduled reconciliation | Runs on demand today | A scheduler (Celery beat or the platform's) |

## 2. Security and privacy

| Improvement | Why |
|---|---|
| Multi-factor authentication | Password-only sign-in; NIST recommends 15+ characters in that case |
| HttpOnly-cookie session with refresh tokens | Bearer token in sessionStorage is readable by page scripts; 30-minute sessions |
| Invitations for people not yet registered | Members must register before they can be added |
| Self-service password change and reset | Not offered |
| Secrets manager integration and bulk re-encryption of connector credentials | Key rotation needs credentials re-saved one by one |
| Field-level masking of personal data for low-privilege roles | Viewers see work emails and names |
| Retention jobs for audit, security events, events, attempts and executions | Tables grow without bound; the triggers already provide the switch for deletion |
| SSRF allowlist by resolved IP, not host name | Host names only today |

## 3. Processing and scale

| Improvement | Why |
|---|---|
| Parallel workflow steps | Steps run one after another; independent applications could run in parallel (design in docs/11 section 6) |
| Bulk replay of dead letters | One entry at a time after a long outage |
| Per-employee ordering across workers | Not guaranteed today (safe because steps read current state) |
| Trigram index (`pg_trgm`) for substring search | 38 ms at 10,000 employees on the test machine, growing linearly |
| Partial index or caching for the organization summary | 40 ms at 10,000 employees |
| Concurrent load testing | Only sequential latency was measured |
| Partitioning of event and attempt tables by time or organization | For very large tenants |

## 4. Operations

| Improvement | Why |
|---|---|
| Prometheus metrics and OpenTelemetry traces | JSON endpoints and logs only |
| Alerting integration | `system/status` must be polled by an external monitor |
| Infrastructure as code (Terraform, Kubernetes manifests) | The deployment guide describes what to provision but nothing provisions it |
| Image publishing to a registry from CI, with vulnerability scanning | CI builds images but does not publish them |
| A setting to disable `/docs` in production | Served in every environment; must be restricted at the proxy today |

## 5. Product

| Improvement | Why |
|---|---|
| Rehiring (reactivating a terminated employee) | Termination is final; a new record is needed |
| More connectors (identity providers such as Okta or Entra ID, project tools) | The adapter interface is ready for them |
| Workflow conditions (for example "only for Engineering") | Every active workflow for a trigger runs for every employee |
| Live updates in the UI (server-sent events) | Screens poll |
| Internationalization of the UI | English only |
