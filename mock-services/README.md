# Mock external services (SIMULATED)

Local stand-ins for the applications SyncForge integrates with, so the whole system can be
run and demonstrated without paid accounts. **These are simulations, not the real services.**
They keep data in memory (restarting a mock clears it) and must never be exposed publicly.

| Mock | Module | Port | Shape it follows | Auth it expects (local defaults) |
|---|---|---|---|---|
| Slack | `mockservices.slack` | 9101 | Slack SCIM v2 user provisioning | `Authorization: Bearer xoxp-mock-local-token` |
| Google Workspace | `mockservices.google_workspace` | 9102 | Admin SDK Directory API `users` | OAuth 2.0 client credentials: `syncforge-local` / `mock-google-client-secret` |
| Payroll | `mockservices.payroll` | 9103 | Generic REST payroll API | `X-API-Key: pk_mock_local_payroll_key` |

The defaults can be changed with environment variables: `SLACK_MOCK_TOKEN`,
`GOOGLE_MOCK_CLIENT_ID`, `GOOGLE_MOCK_CLIENT_SECRET`, `GOOGLE_MOCK_TOKEN_TTL` (seconds) and
`PAYROLL_MOCK_API_KEY`.

## Run

From the repository root, with the backend virtual environment active (it already has
FastAPI and uvicorn; `pip install -r mock-services/requirements.txt` otherwise), one
terminal per mock:

```powershell
uvicorn mockservices.slack:app --port 9101 --app-dir mock-services
uvicorn mockservices.google_workspace:app --port 9102 --app-dir mock-services
uvicorn mockservices.payroll:app --port 9103 --app-dir mock-services
```

Each mock has its own Swagger UI, e.g. http://127.0.0.1:9101/docs.

## Failure injection

Every mock exposes the same control API (no authentication - local use only):

| Request | Effect |
|---|---|
| `POST /_mock/faults` `{"kind": "status", "status": 503, "count": 2}` | Next 2 API requests return 503 |
| `POST /_mock/faults` `{"kind": "rate_limit", "retry_after": 5}` | Next request returns 429 with `Retry-After: 5` |
| `POST /_mock/faults` `{"kind": "timeout", "delay_seconds": 15}` | Next request waits 15 s before answering (longer than SyncForge's read timeout) |
| optional `"path_prefix": "/scim/v2/Users"` | Only requests under that path are affected |
| `DELETE /_mock/faults` | Clear queued faults |
| `POST /_mock/reset` | Clear faults, stored users and the request log |
| `GET /_mock/state` | Queued faults, user count, and a log of `{method, path, status}` |
| `POST /_mock/expire-tokens` (Google only) | Invalidate every issued OAuth token |

A **timeout fault still performs the operation** after the delay - like a real API that
was slow rather than down. The client sees a timeout even though the user was created,
which is exactly the situation idempotent retries (Phase 6) must handle.

PowerShell example:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:9101/_mock/faults -ContentType "application/json" `
  -Body '{"kind":"status","status":503,"count":1}'
```

The request log records only method, path and status - never bodies or headers, which carry
tokens and personal data.

## Tests

`backend/tests/mock_servers.py` starts all three mocks as real HTTP servers on free ports
for the connector tests, so timeouts, connection errors and status codes travel over real
sockets.
