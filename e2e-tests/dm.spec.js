const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const EMAIL = process.env.E2E_EMAIL || 'e2e-fresh@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'fresh1234';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard', { timeout: 15000 });
}

test.describe('Direct messages', () => {
  test('parent can open inbox + see new-thread form', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/dm`);
    await expect(page.locator('h1')).toContainText(/Mensajes|Direct/i);
    // Form shows when at least one other member exists
    const summary = page.getByText(/Nueva conversación|New thread/i);
    if (await summary.count()) {
      await summary.first().click();
      await expect(page.getByRole('button', { name: /Iniciar|Start/i })).toBeVisible();
    }
  });

  test('thread list link reachable from BottomNav chat is /chat (not /dm)', async ({ page }) => {
    // sanity: chat icon points to family chat, DM is separate page
    await login(page);
    await page.goto(`${BASE_URL}/dashboard`);
    const chatLink = page.locator('nav a[href="/chat"]');
    await expect(chatLink).toBeVisible();
  });
});
