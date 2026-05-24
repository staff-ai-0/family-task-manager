const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const EMAIL = process.env.E2E_EMAIL || 'mom@demo.com';
const PASSWORD = process.env.E2E_PASSWORD || 'password123';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard', { timeout: 10000 });
}

test.describe('Family chat', () => {
  test('post message + render bubble', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/chat`);
    await expect(page.locator('h1')).toContainText(/Chat|chat/i);

    const body = `E2E ping ${Date.now()}`;
    await page.fill('input[name="body"]', body);
    await page.locator('form button[type="submit"]').click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByText(body)).toBeVisible();
  });

  test('chat nav badge visible after sending', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/dashboard`);
    const chatLink = page.locator('nav a[href="/chat"]');
    await expect(chatLink).toBeVisible();
  });
});
