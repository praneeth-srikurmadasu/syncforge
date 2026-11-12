# Phase 8 — Frontend testing and quality report

This document records how the Angular application is tested and the results of
the Milestone 9 quality pass. Every number below comes from a run on the date
shown; nothing is estimated.

## Test layers

| Layer | Tool | Location | Command |
|---|---|---|---|
| Unit and component | Vitest via `ng test` | `src/**/*.spec.ts` | `npm run test:ci` |
| Lint, including template accessibility rules | ESLint + angular-eslint | `src/` | `npx ng lint` |
| Formatting | Prettier | `src/`, `e2e/` | `npm run format:check` |
| API contract drift | openapi-typescript | `src/app/core/api/schema.d.ts` | `npm run api:check` |
| Browser, end to end | Playwright 1.65.0 | `e2e/tests/` | `npm run e2e` |
| Automated accessibility | axe-core via `@axe-core/playwright` 4.14.0 | `e2e/tests/quality.spec.ts` | part of `npm run e2e` |
| Size budgets | Angular build budgets | `angular.json` | `npx ng build` |

## How the browser suite works

The browser tests run against the real stack, with no mocking of the SyncForge
API: PostgreSQL, Redis, the FastAPI server, the Celery worker, the outbox relay,
and the three local mock services (Slack, Google Workspace, payroll — all
simulated, see `mock-services/README.md`).

`e2e/support/stack.ts` provisions a fresh tenant for each test through the
public API: it registers a user, creates an organization and departments, and
optionally connects the three simulated connectors and an active onboarding
workflow. Tests therefore never depend on each other or on existing data.
`payrollFault()` uses the payroll mock's fault endpoint to force HTTP 503
responses for the reliability test and always switches it off afterwards.

Tests run with one worker, because they share the single local worker and mock
services; parallel runs would make the timing of asynchronous steps
unpredictable.

## Browser test inventory

| Spec | Test | What it proves |
|---|---|---|
| auth | register with an 8-character password, reveal it, land on onboarding | Password rules, show/hide toggle, first-organization flow |
| auth | a wrong password is refused with a clear message | Error is shown, not swallowed |
| auth | a deep link survives sign-in, and sign-out revokes the session | `returnUrl`, server-side logout |
| auth | an organization the user does not belong to is not shown | Organization isolation in the UI (membership checked by the API) |
| workforce | add, edit with a concurrent change, terminate and archive an employee | Form validation, HTTP 412 on a stale edit with "load latest", lifecycle |
| workforce | search and filters are kept in the URL | Shareable, reload-safe list state |
| integrations | connect Slack from the catalog and test the connection | Schema-driven form; a wrong token fails the test call visibly |
| integrations | build and activate an onboarding workflow, then a hire is provisioned | Builder, activation, event completed with three steps |
| reliability | a failing step is dead-lettered, then replayed to completion | Retries exhausted → dead letter → replay → completed |
| governance | a department changed in payroll becomes a conflict that is resolved | Reconcile detects the conflict; resolution recorded |
| governance | a viewer sees read-only screens and cannot open the audit log | RBAC: hidden actions, forbidden route |
| quality | no serious accessibility violations, in the dark and the light theme | axe WCAG 2 A/AA, serious and critical impacts, 14 pages × 2 themes |
| quality | pages fit a 390 px wide phone screen without horizontal scrolling | Same 14 pages |

Pages covered by the quality tests: dashboard, employees, departments,
reporting, connectors, workflows, events, reliability, dead-letters, conflicts,
policies, audit, team, settings. The chart canvas (`.plot`) is excluded from axe
because ECharts draws on a canvas; its data is exposed to screen readers as a
hidden table that axe does check.

## Defects found and fixed in Milestone 9

The first full run (4 passed, 9 failed) found real defects as well as test
mistakes. All are fixed.

### Application defects

1. **Colour contrast below WCAG AA (dark and light themes).** axe reported 20
   failing nodes on the dark dashboard alone, mostly faint and muted text and
   white text on the accent and danger buttons. Token changes in
   `src/styles/_tokens.scss`:

   | Token | Dark before → after | Light before → after |
   |---|---|---|
   | `--sf-text-muted` | `#9099ab` → `#a0a8b8` | `#5b6475` → `#4f5869` |
   | `--sf-text-faint` | `#646d80` → `#868fa2` | `#8a92a3` → `#626a7c` |
   | `--sf-accent` | `#7b77ff` → `#6560ee` | unchanged |
   | `--sf-accent-hover` | `#918eff` → `#5a55e3` (darker, keeps white text legible) | unchanged |
   | `--sf-success` | unchanged | `#13895a` → `#0e754c` |
   | `--sf-warning` | unchanged | `#a86a00` → `#875500` |
   | `--sf-danger` | unchanged | `#cf3434` → `#b52b2b` |
   | `--sf-info` | unchanged | `#1675b8` → `#14679f` |
   | `--sf-danger-solid` (new) | `#c23434` | `#b52b2b` |

   Danger buttons now use `--sf-danger-solid`, because white text on the
   dark-theme danger colour (`#f26d6d`) was below 4.5:1.

2. **Horizontal scrolling on phones.** At 390 px the dashboard measured 445 px,
   departments 522 px, team 668 px and workflows 800 px wide. Causes: the
   chart's screen-reader table ignored its hidden width, and 11 tables in 8
   components were not inside the scrolling `.sf-table-wrap` container. Both
   fixed, and the department "add" form now wraps.

3. **Landmark naming.** The label "Main navigation" was on the `<aside>`, not
   on the `<nav>`, so assistive technology announced the wrong landmark. The
   `<nav>` now carries "Main navigation" and the `<aside>` is labelled
   "Sidebar".

### Test defects

- The workflow builder test selected a connector before the new step row had
  rendered; it now waits for the row count to grow.
- Several selectors were ambiguous (a "Department" filter and a form field with
  the same label; "Connectors" in the sidebar and in a dashboard card; a "New
  workflow" button in both the page header and the empty state). Sidebar clicks
  now go through a `nav()` helper scoped to the "Main navigation" landmark, and
  other selectors are exact or scoped.
- The first four auth failures were `ERR_CONNECTION_REFUSED`: the dev server was
  still compiling. The suite must start after `npm start` reports it is ready.

## Results

Run on 2026-11-12, Linux, Chrome (system binary via `SF_CHROME`), Angular dev
server, local stack as described above.

| Check | Result |
|---|---|
| Browser suite, first run after fixes | 13 passed, 0 failed (2.5 min) |
| Browser suite, second consecutive run | 13 passed, 0 failed (2.5 min) |
| Unit tests | 16 files, 57 tests passed |
| `ng lint` | All files pass linting |
| `format:check` (`src` and `e2e`) | All files formatted |
| Production build | Succeeds within budgets |
| `npm audit --omit=dev` | 0 vulnerabilities |

### Bundle sizes (production build)

| | Raw | Estimated transfer |
|---|---|---|
| Initial total | 351.66 kB | 96.10 kB |
| Largest lazy chunk (`echarts-setup`, loaded only by the dashboard chart) | 561.40 kB | 162.84 kB |

Feature pages are lazy-loaded route chunks; ECharts is never in the initial
bundle.

## Manual checks

- Keyboard: the browser tests drive forms, dialogs and menus through standard
  controls, and dialogs use Angular CDK, which traps focus and returns it on
  close. angular-eslint's template accessibility rules (click handlers need
  keyboard equivalents, interactive elements must be focusable) pass. A full
  manual keyboard-only walkthrough of every page has not been recorded.
- Screen reader: landmarks, headings and form labels are verified by axe; a full
  manual screen-reader pass with NVDA or VoiceOver has not been done and is
  listed as a known gap.

## Known limitations

- The browser suite needs the whole local stack running; CI wiring for it is
  Phase 10 work (Docker Compose and GitHub Actions).
- Only Chromium is tested. Firefox and WebKit are not part of the suite.
- axe finds roughly the machine-detectable share of accessibility issues; it is
  not a substitute for manual testing with assistive technology.
- The dashboard issues several list requests to compute its totals (there is no
  aggregate metrics endpoint). This works, but a single summary endpoint would
  be a sensible backend improvement in Phase 9.
