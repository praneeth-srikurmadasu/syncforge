import { expect, test } from '@playwright/test';
import { MOCK_CREDENTIALS, hire, newTenant, signIn, waitForEvent, nav } from '../support/stack';

test('connect Slack from the catalog and test the connection', async ({ page }) => {
  const t = await newTenant();
  await signIn(page, t);
  await nav(page, 'Connectors');
  await page
    .locator('article', { hasText: 'Slack' })
    .getByRole('button', { name: 'Connect' })
    .click();
  await page.locator('#cred-token').fill(MOCK_CREDENTIALS.slack.token);
  await page.locator('button[form=connector-form]').click();
  await page.getByRole('button', { name: 'Test connection' }).click();
  await expect(page.getByText('Connection works')).toBeVisible();

  await page.getByRole('button', { name: 'Replace credentials' }).click();
  await page.locator('#cred-token').fill('xoxp-not-the-right-token');
  await page.locator('button[form=connector-form]').click();
  await page.getByRole('button', { name: 'Test connection' }).click();
  await expect(page.getByText('Connection failed')).toBeVisible();
  await expect(page.getByText('Check the credentials')).toBeVisible();
});

test('build and activate an onboarding workflow, then a hire is provisioned', async ({ page }) => {
  const t = await newTenant({ connectors: true });
  await signIn(page, t);
  await nav(page, 'Workflows');
  await page.locator('sf-page-header').getByRole('link', { name: 'New workflow' }).click();
  await page.getByLabel('Name').fill('Onboarding');
  const steps = page.locator('select[id^=step-conn-]');
  const names = ['slack', 'google_workspace', 'payroll'];
  for (const [i, name] of names.entries()) {
    await page.getByRole('button', { name: 'Add step' }).click();
    await expect(steps).toHaveCount(i + 1);
    await steps.nth(i).selectOption({ label: `${name} (${name})` });
  }
  await page.getByRole('button', { name: 'Create workflow' }).click();
  await expect(page.getByText('Inactive:')).toBeVisible();
  await page.getByRole('button', { name: 'Activate' }).click();
  await expect(page.getByText('Onboarding is active')).toBeVisible();

  const e = await hire(t);
  await waitForEvent(t, e.id, ['completed']);
  await nav(page, 'Events');
  await page.locator('tbody tr').first().click();
  await expect(page.locator('sf-page-header sf-status')).toContainText('Completed');
  await expect(page.locator('.execution tbody tr')).toHaveCount(3);
});
