# Phase 8 — Angular frontend: completion report

**Status:** complete, 2026-11-12. All figures below come from actual runs; the Windows
results are the project owner's.

## 1. What was built

An Angular 22 administration application in `frontend/` for the existing SyncForge API,
delivered in ten milestones:

| # | Milestone | Commit |
|---|---|---|
| 1–4 | Plan and repository audit; Angular foundation (generated API types, HTTP layer, design system, shell); authentication and organization context; dashboard | `a7e06a7` |
| 5, 5a | Employees, departments, reporting lines; password minimum 8 and show/hide toggle (owner request) | `42fe0cc` |
| 6 | Connectors (schema-driven forms, test, operations, reconcile, disconnect) and the event monitor | `88a1234` |
| 7 | Workflow builder and history, reliability overview, dead-letter queue and replay | `cd54e12` |
| 7a | Collapsible sidebar (owner request) | `95a96a8` |
| 8 | Conflicts and policies, audit log, team and roles, settings | `e06e838` |
| 9 | Browser test suite, accessibility and phone-layout fixes | `60d96af` |
| 10 | Architecture, components and API-integration documents, README, ADR-0020, this report | this commit |

Screens: sign-in, registration, create organization; dashboard; employees
list and detail, departments, reporting lines; connectors list and detail; workflows
list, builder and detail; events list and detail; reliability overview; dead-letter list
and detail; conflicts list and detail; policies; audit log; team and roles; settings;
plus forbidden, unavailable and not-found pages.

Size: 131 source files (`.ts`, `.html`, `.scss`) in `frontend/src`, about 15,800 lines
excluding the generated `schema.d.ts`; 16 unit-test files; 6 browser-test files.

## 2. Requirements check

| Phase 8 rule | How it is met |
|---|---|
| Do not rewrite the backend / change its logic for the UI | No backend logic changed. The only backend change was the password minimum (owner request), with its tests and docs |
| No fake endpoints or success responses | The UI calls 51 of the API's 53 operations (all except `/health` and `/ready`) and nothing else; every success message follows a 2xx |
| No hardcoded metrics or fabricated history | Totals come from `limit=1` list calls; daily history from audit-log windows; unsupported data is left out (plan, section 7) |
| No exposed credentials | Connector credentials are write-only; only fingerprints are shown. No secrets in the frontend |
| RBAC and organization isolation | Route guards and role-aware UI mirror the API; the API enforces both; tested end to end (viewer test, other-organization test) |
| No silently swallowed errors | One `ApiError` path; page error states and toasts with request IDs |
| No non-functional buttons | Every action calls the API; unsupported features are absent and listed in the plan |
| No monolithic component | 60 standalone components; pages own data, shared components present |
| No unnecessary dependencies | Runtime: Angular, CDK, ECharts + ngx-echarts, lucide, two fontsource packages, RxJS. Dev: Angular tooling, ESLint, Prettier, Vitest, Playwright, axe-core |
| Simulated connectors not presented as real | "Simulated" badge on mock-backed connectors; docs point to `mock-services/README.md` |
| Browser storage is not called XSS protection | Stated explicitly in the architecture document and ADR-0020 |

## 3. Verification

### Linux workspace (Node 22.23.4, headless Chrome), 2026-11-12

| Check | Result |
|---|---|
| `npm run test:ci` | 16 files, **57 passed** |
| `npm run e2e` | **13 passed** on two consecutive runs (2.5 min each) |
| `npx ng lint` | All files pass |
| `npm run format:check` (`src`, `e2e`) | All files formatted |
| `npx ng build` | Success; initial 351.66 kB raw / 96.11 kB transfer after milestone 10 (96.10 kB at milestone 9) |
| `npm audit --omit=dev` | 0 vulnerabilities |
| Backend `python -m pytest` | **527 passed** |

### Windows (project owner), 2026-11-12, commit `60d96af`

| Check | Result |
|---|---|
| `npm run e2e` | **13 passed** (4.1 min) |
| `npm run test:ci` | 16 files, **57 passed** |
| `npx ng lint`, `npm run format:check` | Clean |
| `npx ng build` | Success; initial 351.66 kB / 96.10 kB, identical to Linux |

Manual verification by the owner during the phase: sign-up and sign-in, dashboard,
employee management, automatic provisioning of a hire through the simulated connectors,
a dead-lettered event replayed to completion, and the collapsible sidebar.

`npm ci` reports 10 moderate advisories in development-only packages (build and test
tooling); the production dependency tree has none (`npm audit --omit=dev`).

## 4. Defects found by testing and fixed

- Colour contrast below WCAG AA in both themes (milestone 9, axe): tokens adjusted.
- Horizontal scrolling on 390 px screens on four pages: tables in scroll containers.
- "Main navigation" landmark label on the wrong element.
- Earlier milestones: department forms reloading the page (native submit), a missing
  renamed file in a delivery zip, a misleading "simulated connectors accept any
  credentials" note, the dead-letter page listing itself among "other entries", the
  collapsed sidebar breaking the phone drawer. All fixed before delivery.

## 5. Known limitations

| Limitation | Effect | Where it could be addressed |
|---|---|---|
| No aggregate or statistics endpoints | Dashboard makes about 40 small requests | Phase 9: one summary endpoint |
| No push channel | Background progress is followed by polling | Later: server-sent events |
| Bearer token in `sessionStorage`, no refresh token | Sign in again after 30 minutes; token readable by page scripts | Phase 9: HttpOnly cookie session with refresh |
| No invitations | New members must register before they can be added | Backend feature |
| No profile editing or password change | Not offered in the UI | Backend feature |
| No event date filter, no per-employee linked accounts | Not offered (API has no parameters for them) | Backend feature |
| Browser tests need the whole stack running locally; Chromium only | Not yet in CI | Phase 10: Docker Compose and GitHub Actions |
| No recorded manual screen-reader or keyboard-only pass | Automated checks only | Before a production release |
| Production serving (reverse proxy for `/api`) | Dev server only | Phase 10 |

## 6. Documentation

- [PHASE_8_FRONTEND_PLAN.md](PHASE_8_FRONTEND_PLAN.md) — audit, screen-to-endpoint map, unsupported features
- [PHASE_8_FRONTEND_ARCHITECTURE.md](PHASE_8_FRONTEND_ARCHITECTURE.md)
- [PHASE_8_FRONTEND_COMPONENTS.md](PHASE_8_FRONTEND_COMPONENTS.md)
- [PHASE_8_FRONTEND_API_INTEGRATION.md](PHASE_8_FRONTEND_API_INTEGRATION.md)
- [PHASE_8_FRONTEND_TESTING.md](PHASE_8_FRONTEND_TESTING.md)
- [ADR-0020](adr/0020-angular-frontend-signals-and-server-state.md)
- `README.md` (screenshots, running the web application), `frontend/README.md`
  (commands, browser tests), `PROJECT_STATUS.md`, `CHANGELOG.md`

## 7. Next

Phase 9 — security hardening, `/api/v2` versioning demonstration, observability and
performance measurement. Candidates raised by Phase 8: a dashboard summary endpoint and
an HttpOnly-cookie session.
