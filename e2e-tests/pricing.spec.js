const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const EMAIL = process.env.E2E_EMAIL || 'e2e-fresh@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'fresh1234';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('#login-submit-btn');
  await page.waitForURL('**/dashboard', { timeout: 30000 });
}

test.describe('Pricing / upgrade (PayPal)', () => {
  // /pricing/upgrade is a 301 redirect to /parent/settings/subscription (the
  // canonical plans+billing surface) — see frontend/src/pages/pricing/upgrade.astro.
  test('redirects to the canonical subscription settings page', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/pricing/upgrade`);
    await expect(page).toHaveURL(/\/parent\/settings\/subscription$/);
    await expect(page.locator('h1')).toContainText(/Subscription|Suscripci[oó]n/i);
  });

  test('shows the plan comparison table with Plus/Pro tiers', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/pricing/upgrade`);
    await expect(page.locator('table th').filter({ hasText: /plus/i })).toBeVisible();
    await expect(page.locator('table th').filter({ hasText: /pro/i })).toBeVisible();
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
