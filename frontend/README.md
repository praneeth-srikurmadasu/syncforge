# SyncForge frontend

Angular 22 administration application for SyncForge. It talks only to the SyncForge API;
every figure and list on screen comes from an existing backend endpoint.

Architecture, pages, API integration and testing are described in
[`docs/25-frontend.md`](../docs/25-frontend.md).

## Requirements

- Node.js `^22.22.3`, `^24.15.0` or 26+ (the Angular 22 requirement). Built and tested with 22.23.4; Node 24.18 is also in range
- The SyncForge API running on `http://127.0.0.1:8000` (see the repository README)

## Run (Windows PowerShell)

```powershell
Set-Location "$HOME\Projects\syncforge\frontend"
npm ci
npm start
```

Open http://localhost:4200. The development server forwards `/api`, `/health` and
`/ready` to the API (`proxy.conf.json`), so the browser only ever talks to one origin.

## Checks

```powershell
npx ng build              # production build with size budgets
npm run test:ci           # unit tests (Vitest)
npx ng lint               # ESLint + angular-eslint, including template accessibility rules
npm run format:check      # Prettier
npm run api:check         # API types still match openapi/openapi.json
```

## Browser tests (Playwright)

The suite in `e2e/` drives the real application in Chromium against the real
API, worker, outbox relay and mock services. It creates its own users and
organizations through the API, so it never touches your existing data.

One-time setup:

```powershell
npx playwright install chromium
```

Start all five processes first (Postgres and Redis in Docker, the mock
services, the API, the worker, the relay) and `npm start`, then:

```powershell
npm run e2e          # 13 tests, about 3 minutes
npm run e2e:report   # open the HTML report of the last run
```

Environment variables, all optional: `SF_WEB` (default `http://localhost:4200`),
`SF_API` (default `http://127.0.0.1:8000/api/v1`), `SF_CHROME` (path to a
Chrome binary to use instead of Playwright's Chromium).

What is covered: sign-up and sign-in, organization isolation, employee
lifecycle with a concurrent edit, connecting and testing connectors, building
and activating a workflow, a hire provisioned end to end, a dead letter
replayed to completion, a conflict reconciled and resolved, viewer RBAC,
automated accessibility checks (axe, WCAG 2 A/AA) on 14 pages in both themes,
and a 390 px phone layout check on the same pages.

## API types

`src/app/core/api/schema.d.ts` is generated from the backend's OpenAPI document and must not
be edited by hand. After a backend API change, refresh the snapshot and regenerate:

```powershell
Set-Location "$HOME\Projects\syncforge\backend"
& "$HOME\Projects\syncforge\backend\.venv\Scripts\python.exe" -c "import json; from app.main import app; open('../frontend/openapi/openapi.json', 'w', encoding='utf-8', newline='\n').write(json.dumps(app.openapi(), indent=2, sort_keys=True) + '\n')"
Set-Location "$HOME\Projects\syncforge\frontend"
npm run api:types
```

`openapi-typescript` runs through `npx` (it is not installed as a dependency: its peer range
does not yet include TypeScript 6).

## Structure

```
src/app/
  core/       API client and types, session and guards, organization context, theme, toasts
  shared/     design system components, chart wrapper, form helpers
  layout/     application shell (sidebar, top bar, organization switcher)
  features/   one folder per area (auth, dashboard, ...), lazy-loaded
src/styles/   design tokens (dark and light themes) and shared control styles
```
