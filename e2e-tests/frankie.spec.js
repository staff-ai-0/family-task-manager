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

test.describe('Frankie copilot', () => {
  test('parent can open chat page and see input', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/parent/frankie`);
    await expect(page.locator('h1')).toContainText('Frankie');
    await expect(page.locator('#message-input')).toBeVisible();
  });

  test('sends a message and gets a response or graceful error', async ({ page }) => {
    test.skip(!process.env.E2E_FULL, 'requires LITELLM_API_KEY in backend');
    await login(page);
    await page.goto(`${BASE_URL}/parent/frankie`);
    await page.fill('#message-input', 'What needs my attention today?');
    await page.locator('#chat-form button[type="submit"]').click();
    // Bot reply bubble appears within 30s, or alert pops with error
    await page.waitForTimeout(2000);
    const bubbles = page.locator('main .bg-brand-cream.border');
    await expect(bubbles).toHaveCount(2, { timeout: 30000 });
  });
});
