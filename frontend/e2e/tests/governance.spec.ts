import { expect, request, test } from '@playwright/test';
import {
  API,
  MOCK_CREDENTIALS,
  PAYROLL_MOCK,
  hire,
  newTenant,
  signIn,
  unique,
  url,
  waitForEvent,
  nav,
} from '../support/stack';

test('a department changed in payroll becomes a conflict that is resolved', async ({ page }) => {
  const t = await newTenant({ onboarding: true });
  const e = await hire(t, { department_id: t.departments['Engineering'] });
  await waitForEvent(t, e.id, ['completed']);
  const accounts = await (
    await t.api.get(url(t, `connectors/${t.connectors['payroll']}/accounts`))
  ).json();
  const externalId = accounts.items[0].external_id as string;
  const mock = await request.newContext();
  const changed = await mock.patch(`${PAYROLL_MOCK}/v1/employees/${externalId}`, {
    headers: { 'X-API-Key': MOCK_CREDENTIALS.payroll.api_key },
    data: { department: 'Finance' },
  });
  expect(changed.ok()).toBe(true);

  await signIn(page, t);
  await page.goto(`/o/${t.orgId}/connectors/${t.connectors['payroll']}`);
  await page.getByRole('button', { name: 'Reconcile' }).click();
  await expect(page.getByText('New conflicts: 1')).toBeVisible();
  await nav(page, 'Conflicts');
  await page.locator('tbody tr').first().click();
  await expect(page.getByText('Authoritative by policy')).toBeVisible();

  await page.getByText("Use payroll's value").click();
  await expect(page.getByRole('button', { name: 'Resolve conflict' })).toBeDisabled();
  await page.getByText("Keep SyncForge's value").click();
  await page.getByRole('button', { name: 'Resolve conflict' }).click();
  await expect(page.locator('sf-page-header sf-status').first()).toContainText('Resolved');

  const record = await (
    await mock.get(`${PAYROLL_MOCK}/v1/employees/${externalId}`, {
      headers: { 'X-API-Key': MOCK_CREDENTIALS.payroll.api_key },
    })
  ).json();
  expect(record.department).toBe('Engineering');
  await mock.dispose();
});

test('a viewer sees read-only screens and cannot open the audit log', async ({ page }) => {
  const t = await newTenant();
  const email = `${unique('viewer')}@example.com`;
  const anon = await request.newContext();
  await anon.post(`${API}/auth/register`, {
    data: { email, password: 'viewer-pass-1', full_name: 'Vera Viewer' },
  });
  await anon.dispose();
  await t.api.post(url(t, 'members'), { data: { email, role: 'viewer' } });

  await signIn(page, t, email, 'viewer-pass-1');
  const nav = page.getByRole('navigation', { name: 'Main navigation' });
  await expect(nav.getByRole('link', { name: 'Employees' })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Audit log' })).toHaveCount(0);
  await page.goto(`/o/${t.orgId}/audit`);
  await expect(page).toHaveURL(new RegExp(`/o/${t.orgId}/forbidden$`));
  await page.goto(`/o/${t.orgId}/employees`);
  await expect(page.getByRole('heading', { name: 'Employees', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add employee' })).toHaveCount(0);
  await page.goto(`/o/${t.orgId}/policies`);
  await expect(
    page.getByText('Only organization administrators can change policies.'),
  ).toBeVisible();
});
