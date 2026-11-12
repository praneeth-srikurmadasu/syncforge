# 21 - Troubleshooting

> **Scope:** problems actually met while building and running SyncForge (Phases 1-4), with
> their causes and fixes. Later phases add their own entries.

## Investigating a failed request

Every response has an `X-Request-ID` header and every error body has `error.request_id`.
Search the API log for that ID: every line written while handling the request carries it,
including connector calls (`syncforge.connectors`) and the outbound HTTP request (`httpx2`).

## Connectors

| Symptom | Cause | Fix |
|---|---|---|
| Creating a connector returns `503 encryption_not_configured` | `CONNECTOR_ENCRYPTION_KEY` is missing or blank in `.env` | Generate a key (README, Quick start) and restart the API |
| Connection test returns `ok: false`, `error.category: "network"` or `"timeout"` with `connect_timeout` | The mock service (or the real API) is not running, or is on another port | Start the mock (`mock-services/README.md`); check the connector's base URL |
| Connection test or operation fails with `category: "server"` although the mock is running | A fault queued earlier is still waiting (faults survive until used) | `GET http://127.0.0.1:9101/_mock/state` shows queued faults; `DELETE .../_mock/faults` clears them |
| `category: "authentication"` | Wrong credentials for that connector | Rotate them with `PATCH .../connectors/{id}` and test again |
| `422 host_not_allowed` when saving a base URL | The host is not in `CONNECTOR_ALLOWED_HOSTS` (SSRF protection) | Add the host to the allowlist only if it is a trusted vendor endpoint |
| Every connector call takes about 2 seconds on Windows | The base URL uses `localhost`, which Windows tries over IPv6 first | Use `127.0.0.1` (the default since Phase 4); fix any `*_BASE_URL=http://localhost:...` lines in `.env` |

## Tests

| Symptom | Cause | Fix |
|---|---|---|
| Every test errors at setup | PostgreSQL is not running | `docker compose up -d postgres` |
| Windows asks whether Python may use the network during tests | The connector tests start the mocks as local HTTP servers on `127.0.0.1` | Allow on private networks only |
| A refused-connection test reports `timeout` instead of `network` on Windows | Windows retries refused loopback connections for ~2 s | Already handled: that test uses a 5 s connect timeout (docs/10, section 13) |

## Git and the terminal (Windows)

| Symptom | Cause | Fix |
|---|---|---|
| `git log` output ends with `:` and waits | Git opened its pager | Press `q`; use `git --no-pager log ...` or `git config core.pager ""` |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | PowerShell execution policy | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`, then activate again |
