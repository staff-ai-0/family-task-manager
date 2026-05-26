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

test.describe('Kiosk admin', () => {
  test('parent can create a wall display and see token URL', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/parent/kiosk`);
    await expect(page.locator('h1')).toContainText(/Wall|Pantalla/i, { timeout: 10000 });

    const name = `Kitchen ${Date.now()}`;
    await page.fill('input[name="name"]', name);
    await page.getByRole('button', { name: /create|crear/i }).click();
    await page.waitForLoadState('networkidle');

    // Token URL banner appears once
    await expect(page.getByText(/Save this URL|Guarda esta URL/i)).toBeVisible();
    await expect(page.locator('code')).toContainText('/kiosk?token=');

    // Device row also visible
    await expect(page.getByText(name)).toBeVisible();
  });
});
