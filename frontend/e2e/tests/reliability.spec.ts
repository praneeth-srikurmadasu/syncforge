import { expect, test } from '@playwright/test';
import { hire, newTenant, payrollFault, signIn, waitForEvent } from '../support/stack';

test.afterEach(async () => payrollFault(false));

test('a failing step is dead-lettered, then replayed to completion', async ({ page }) => {
  const t = await newTenant({ onboarding: true });
  await payrollFault(true);
  const e = await hire(t);
  await waitForEvent(t, e.id, ['dead_letter'], 90);
  await payrollFault(false);

  await signIn(page, t);
  await page.getByRole('link', { name: 'Dead-letter queue' }).click();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody tr')).toContainText('Retries exhausted');
  await page.locator('tbody tr').first().click();
  await page.getByRole('button', { name: 'Replay' }).click();
  await page.locator('sf-confirm-dialog').getByRole('button', { name: 'Replay' }).click();
  await expect(page.getByText(/^Replayed/)).toBeVisible();

  await waitForEvent(t, e.id, ['completed']);
  await page.getByRole('link', { name: 'Follow the event' }).click();
  await expect(page.locator('sf-page-header sf-status')).toContainText('Completed');
});
