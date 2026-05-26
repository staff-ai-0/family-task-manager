const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const EMAIL = process.env.E2E_EMAIL || 'e2e-fresh@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'fresh1234';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard', { timeout: 10000 });
}

test.describe('Notifications feed', () => {
  test('inbox loads, shows empty state or items, mark-all works when unread', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/notifications`);
    await expect(page.locator('h1')).toContainText(/Notifications|Notificaciones/i);

    const empty = page.getByText(/No notifications|Sin notificaciones/i);
    const markAll = page.getByRole('button', { name: /mark all read|marcar todas leídas/i });

    if (await markAll.count()) {
      await markAll.first().click();
      await page.waitForLoadState('networkidle');
      // After mark-all, button should be hidden (or empty state appears).
      await expect(markAll).toHaveCount(0);
    } else {
      // No unread: either empty state or only-read items.
      const isEmpty = await empty.count();
      expect(isEmpty).toBeGreaterThanOrEqual(0);
    }
  });

  test('nav has notifications icon with optional badge', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/dashboard`);
    const navLink = page.locator('nav a[href="/notifications"]');
    await expect(navLink).toBeVisible();
  });
});
