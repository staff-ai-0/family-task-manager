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
    // sanity: chat icon points to family chat, DM is separate page.
    // For a parent, chat is not a direct BottomNav item — it lives inside
    // the "More" sheet (MoreSheet.astro, a plain <div> dialog, not a <nav>).
    await login(page);
    await page.goto(`${BASE_URL}/dashboard`);
    await page.locator('#more-nav-btn').click();
    const chatLink = page.locator('#more-sheet a[href="/chat"]');
    await expect(chatLink).toBeVisible();
  });
});
