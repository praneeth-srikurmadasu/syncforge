import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { hire, newTenant, signIn } from '../support/stack';

const PAGES = [
  'dashboard',
  'employees',
  'departments',
  'reporting',
  'connectors',
  'workflows',
  'events',
  'reliability',
  'dead-letters',
  'conflicts',
  'policies',
  'audit',
  'team',
  'settings',
];

test('no serious accessibility violations, in the dark and the light theme', async ({ page }) => {
  test.setTimeout(240_000);
  const t = await newTenant({ connectors: true });
  await hire(t);
  for (const theme of ['dark', 'light']) {
    await page.addInitScript((value) => localStorage.setItem('sf.theme', value), theme);
    await signIn(page, t);
    for (const path of PAGES) {
      await page.goto(`/o/${t.orgId}/${path}`);
      await page.waitForLoadState('networkidle');
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa'])
        .exclude('.plot') // chart canvases; their data is in a visually hidden table
        .analyze();
      const serious = results.violations.filter((v) =>
        ['serious', 'critical'].includes(v.impact ?? ''),
      );
      expect(
        serious.map((v) => `${theme} /${path}: ${v.id} (${v.nodes.length}) ${v.help}`),
      ).toEqual([]);
    }
    await page.context().clearCookies();
    await page.evaluate(() => sessionStorage.clear());
  }
});

test('pages fit a 390 px wide phone screen without horizontal scrolling', async ({ page }) => {
  test.setTimeout(180_000);
  const t = await newTenant({ connectors: true });
  await hire(t);
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, t);
  const overflowing: string[] = [];
  for (const path of PAGES) {
    await page.goto(`/o/${t.orgId}/${path}`);
    await page.waitForLoadState('networkidle');
    // Wide data tables scroll inside their own container by design; the page itself must not.
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    if (width > 391) overflowing.push(`${path}: ${width}px`);
  }
  expect(overflowing).toEqual([]);
});
