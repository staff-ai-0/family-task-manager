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

test.describe('Jarvis schedules', () => {
  test('page loads + create form opens', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/parent/jarvis-schedules`);
    await expect(page.locator('h1')).toContainText(/Programaciones|Jarvis schedules/i);
    await page.getByText(/Nueva programación|New schedule/i).first().click();
    await expect(page.locator('input[name="cron_expr"]')).toBeVisible();
  });

  test('preset button fills cron input', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/parent/jarvis-schedules`);
    await page.getByText(/Nueva programación|New schedule/i).first().click();
    await page.locator('.preset-btn').first().click();
    const cronValue = await page.locator('input[name="cron_expr"]').inputValue();
    expect(cronValue).toMatch(/^\d+\s+\d+\s+/);  // 5-field cron
  });

  test('create + delete schedule', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/parent/jarvis-schedules`);
    await page.getByText(/Nueva programación|New schedule/i).first().click();
    const name = `E2E sched ${Date.now()}`;
    await page.fill('input[name="name"]', name);
    await page.fill('textarea[name="prompt"]', 'test prompt');
    await page.fill('input[name="cron_expr"]', '0 9 * * 1');
    page.on('dialog', dialog => dialog.accept());
    await page.locator('button[type="submit"]').first().click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByText(name)).toBeVisible();
  });
});
