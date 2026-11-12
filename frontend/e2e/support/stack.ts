import { APIRequestContext, Page, expect, request } from '@playwright/test';

export const API = process.env['SF_API'] ?? 'http://127.0.0.1:8000/api/v1';
export const PAYROLL_MOCK = process.env['SF_PAYROLL_MOCK'] ?? 'http://127.0.0.1:9103';
export const PASSWORD = 'e2e-pass-123';

/** Credentials the local mock services accept (mock-services/README.md). */
export const MOCK_CREDENTIALS = {
  slack: { token: 'xoxp-mock-local-token' },
  google_workspace: { client_id: 'syncforge-local', client_secret: 'mock-google-client-secret' },
  payroll: { api_key: 'pk_mock_local_payroll_key' },
} as const;

let counter = 0;
export function unique(prefix: string): string {
  counter += 1;
  return `${prefix}${Date.now().toString(36)}${counter}`;
}

export interface Tenant {
  api: APIRequestContext;
  email: string;
  orgId: string;
  connectors: Record<string, string>;
  departments: Record<string, string>;
}

/** A fresh user who owns a fresh organization, set up through the public API. */
export async function newTenant(
  options: { connectors?: boolean; onboarding?: boolean } = {},
): Promise<Tenant> {
  const email = `${unique('e2e')}@example.com`;
  const anon = await request.newContext();
  const reg = await anon.post(`${API}/auth/register`, {
    data: { email, password: PASSWORD, full_name: 'E2E Admin' },
  });
  expect(reg.status(), await reg.text()).toBe(201);
  const login = await anon.post(`${API}/auth/login`, { data: { email, password: PASSWORD } });
  const token = (await login.json()).access_token as string;
  await anon.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const org = await (
    await api.post(`${API}/organizations`, { data: { name: `E2E ${unique('org')}` } })
  ).json();
  const tenant: Tenant = { api, email, orgId: org.id, connectors: {}, departments: {} };

  for (const name of ['Engineering', 'Finance']) {
    const d = await (await api.post(url(tenant, 'departments'), { data: { name } })).json();
    tenant.departments[name] = d.id;
  }
  if (options.connectors || options.onboarding) {
    for (const [type, credentials] of Object.entries(MOCK_CREDENTIALS)) {
      const res = await api.post(url(tenant, 'connectors'), {
        data: { connector_type: type, name: type, config: {}, credentials },
      });
      expect(res.status(), await res.text()).toBe(201);
      const c = await res.json();
      tenant.connectors[type] = c.id;
      await api.post(url(tenant, `connectors/${c.id}/test`));
    }
  }
  if (options.onboarding) {
    const wf = await (
      await api.post(url(tenant, 'workflows'), {
        data: {
          name: 'Onboarding',
          trigger_event_type: 'employee.created',
          steps: Object.values(tenant.connectors).map((id) => ({
            connector_id: id,
            operation: 'create_user',
          })),
        },
      })
    ).json();
    const act = await api.post(url(tenant, `workflows/${wf.id}/activate`));
    expect(act.status(), await act.text()).toBe(200);
  }
  return tenant;
}

export function url(t: Tenant, path: string): string {
  return `${API}/organizations/${t.orgId}/${path}`;
}

export async function hire(
  t: Tenant,
  extra: Record<string, unknown> = {},
): Promise<{ id: string; full_name: string; employee_number: string }> {
  const n = unique('E');
  const res = await t.api.post(url(t, 'employees'), {
    headers: { 'Idempotency-Key': n },
    data: {
      first_name: 'Ada',
      last_name: n,
      email: `${n.toLowerCase()}@example.com`,
      employee_number: n,
      joining_date: '2026-11-01',
      ...extra,
    },
  });
  expect(res.status(), await res.text()).toBe(201);
  return res.json();
}

/** Waits until the employee's newest event reaches one of the given statuses. */
export async function waitForEvent(
  t: Tenant,
  employeeId: string,
  statuses: string[],
  seconds = 60,
) {
  for (let i = 0; i < seconds; i++) {
    const page = await (
      await t.api.get(url(t, 'events'), { params: { employee_id: employeeId } })
    ).json();
    if (page.items[0] && statuses.includes(page.items[0].status)) return page.items[0];
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`event for ${employeeId} did not reach ${statuses.join('/')} in ${seconds}s`);
}

export async function signIn(page: Page, t: Tenant, email = t.email, password = PASSWORD) {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL(`**/o/${t.orgId}/dashboard`);
}

export async function payrollFault(on: boolean): Promise<void> {
  const ctx = await request.newContext();
  if (on) {
    const res = await ctx.post(`${PAYROLL_MOCK}/_mock/faults`, {
      data: { kind: 'status', status: 503, count: 1000, path_prefix: '/v1/employees' },
    });
    expect(res.ok()).toBe(true);
  } else {
    await ctx.delete(`${PAYROLL_MOCK}/_mock/faults`);
  }
  await ctx.dispose();
}

/** Clicks a sidebar link, never a same-named link in page content. */
export async function nav(page: Page, name: string): Promise<void> {
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('link', { name, exact: true })
    .click();
}
