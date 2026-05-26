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

test.describe('Calendar', () => {
  test('agenda → month nav, create event', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/calendar`);
    await expect(page.locator('h1')).toContainText(/Calendar|Calendario/i);

    // Open the create-event details
    await page.getByText(/New event|Nuevo evento/i).first().click();
    const title = `E2E event ${Date.now()}`;
    await page.fill('input[name="title"]', title);
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    const dateStr = tomorrow.toISOString().slice(0, 10);
    await page.fill('input[name="date"]', dateStr);
    await page.fill('input[name="time"]', '15:00');
    await page.locator('button[type="submit"]', { hasText: /add|agregar/i }).first().click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByText(title)).toBeVisible();

    // Switch to month view
    await page.getByRole('link', { name: /month view|vista mes/i }).click();
    await page.waitForURL('**/calendar/month*');
    await expect(page.locator('main')).toBeVisible();
  });
});
