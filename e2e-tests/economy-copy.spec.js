const { test, expect } = require('@playwright/test');
const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';

async function login(page, email, pw) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', pw);
  await page.click('#login-submit-btn');
  await page.waitForURL('**/dashboard', { timeout: 30000 });
}

test('kid dashboard economy banner uses v2 copy (no "never become cash")', async ({ page }) => {
  await login(page, 'emma@demo.com', 'password123');
  const body = await page.locator('body').innerText();
  expect(body).not.toContain('nunca se vuelven dinero');
  expect(body).not.toContain('never turn into cash');
  // v2 mentions the domingo/allowance unlock
  expect(body.toLowerCase()).toMatch(/domingo|allowance|desbloqu|unlock/);
});
