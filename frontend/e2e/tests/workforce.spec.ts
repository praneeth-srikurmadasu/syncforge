import { expect, test } from '@playwright/test';
import { hire, newTenant, signIn, unique, url, nav } from '../support/stack';

test('add, edit with a concurrent change, terminate and archive an employee', async ({ page }) => {
  const t = await newTenant();
  await signIn(page, t);
  await nav(page, 'Employees');
  await page.getByRole('button', { name: 'Add employee' }).first().click();
  const number = unique('QA');
  await page.getByLabel('First name').fill('Grace');
  await page.getByLabel('Last name').fill('Hopper');
  await page.getByLabel('Work email').fill(`${number.toLowerCase()}@example.com`);
  await page.getByLabel('Employee number').fill(number);
  await page.locator('#ef-dept').selectOption({ label: 'Engineering' });
  await page.locator('button[form=employee-form]').click();
  await expect(page.getByRole('heading', { name: 'Grace Hopper' })).toBeVisible();
  const id = page.url().split('/').pop()!;

  // Someone else changes the record while the edit dialog is open.
  await page.getByRole('button', { name: 'Edit' }).click();
  await page.getByLabel('Designation').fill('Rear Admiral');
  const current = await (await t.api.get(url(t, `employees/${id}`))).json();
  const other = await t.api.patch(url(t, `employees/${id}`), {
    headers: { 'If-Match': `"${current.version}"` },
    data: { location: 'Arlington' },
  });
  expect(other.status()).toBe(200);
  await page.locator('button[form=employee-form]').click();
  await expect(page.getByText('Someone else changed this employee')).toBeVisible();
  await page.getByRole('button', { name: 'Load latest version' }).click();
  await expect(page.getByLabel('Location')).toHaveValue('Arlington');
  await page.getByLabel('Designation').fill('Rear Admiral');
  await page.locator('button[form=employee-form]').click();
  await expect(page.getByText('Changes saved')).toBeVisible();

  await page.getByRole('button', { name: 'Terminate' }).click();
  await page.getByLabel(/Type .* to confirm/).fill(number);
  await page.getByRole('button', { name: 'Terminate employee' }).click();
  await expect(page.getByText(/Terminated on/)).toBeVisible();
  await page.getByRole('button', { name: 'Archive' }).click();
  await page.locator('sf-confirm-dialog').getByRole('button', { name: 'Archive' }).click();
  await expect(page).toHaveURL(new RegExp(`/o/${t.orgId}/employees$`));
});

test('search and filters are kept in the URL', async ({ page }) => {
  const t = await newTenant();
  const e = await hire(t, { last_name: 'Searchable', department_id: t.departments['Finance'] });
  await hire(t);
  await signIn(page, t);
  await page.getByPlaceholder('Search employees').fill('Searchable');
  await page.getByPlaceholder('Search employees').press('Enter');
  await expect(page).toHaveURL(/search=Searchable/);
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody tr')).toContainText(e.employee_number);
  await page.reload();
  await expect(page.locator('tbody tr')).toHaveCount(1);
});
