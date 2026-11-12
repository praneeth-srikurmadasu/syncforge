import { expect, test } from '@playwright/test';
import { PASSWORD, newTenant, signIn, unique } from '../support/stack';

test('register with an 8-character password, reveal it, land on onboarding', async ({ page }) => {
  await page.goto('/register');
  await page.getByLabel('Full name').fill('Grace Hopper');
  await page.getByLabel('Work email').fill(`${unique('reg')}@example.com`);
  await page.getByLabel('Password', { exact: true }).fill('abcd1234');
  await page.getByLabel('Confirm password').fill('abcd1234');
  await page.getByRole('button', { name: 'Show password' }).first().click();
  await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute('type', 'text');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page).toHaveURL(/\/organizations\/new$/);
  await page.getByLabel('Name', { exact: true }).fill(`QA ${unique('o')}`);
  await page.getByRole('button', { name: 'Create organization' }).click();
  await expect(page).toHaveURL(/\/o\/.+\/dashboard$/);
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
});

test('a wrong password is refused with a clear message', async ({ page }) => {
  const t = await newTenant();
  await page.goto('/login');
  await page.getByLabel('Email').fill(t.email);
  await page.getByLabel('Password', { exact: true }).fill('not-the-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toContainText('The email or password is incorrect.');
});

test('a deep link survives sign-in, and sign-out revokes the session', async ({ page }) => {
  const t = await newTenant();
  await page.goto(`/o/${t.orgId}/departments`);
  await expect(page).toHaveURL(/\/login\?returnUrl=/);
  await page.getByLabel('Email').fill(t.email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(new RegExp(`/o/${t.orgId}/departments$`));

  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto(`/o/${t.orgId}/dashboard`);
  await expect(page).toHaveURL(/\/login\?returnUrl=/);
});

test('an organization the user does not belong to is not shown', async ({ page }) => {
  const mine = await newTenant();
  const other = await newTenant();
  await signIn(page, mine);
  await page.goto(`/o/${other.orgId}/dashboard`);
  await expect(page.getByRole('heading', { name: 'Organization not available' })).toBeVisible();
});
