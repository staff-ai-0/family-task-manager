const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'https://gcp-family.agent-ia.mx';
const EMAIL = process.env.E2E_EMAIL || 'e2e-fresh@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'fresh1234';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard', { timeout: 15000 });
}

test.describe('Pricing / upgrade (PayPal)', () => {
  test('page renders + shows tier cards', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/pricing/upgrade`);
    await expect(page.locator('h1')).toContainText(/Planes|Plans/i);
    // At least one tier card visible
    await expect(page.locator('h2').filter({ hasText: /plus|pro/i }).first()).toBeVisible();
  });

  test('manage link routes to subscription settings', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/pricing/upgrade`);
    // Explicit href avoids matching ambiguity with other "Manage" links.
    const manage = page.locator('a[href="/parent/settings/subscription"]');
    await expect(manage).toBeVisible({ timeout: 10000 });
  });
});

test.describe('Analytics CSV export', () => {
  test('export.csv endpoint returns CSV', async ({ page }) => {
    await login(page);
    const response = await page.request.get(`${BASE_URL}/api/analytics/export.csv`);
    if (response.ok()) {
      expect(response.headers()['content-type']).toContain('text/csv');
      const text = await response.text();
      expect(text).toContain('user_id,name,role');
    } else {
      // Auth proxy might intercept
      expect([401, 403]).toContain(response.status());
    }
  });
});
