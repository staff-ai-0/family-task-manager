const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const DEMO_USER = {
  email: process.env.E2E_EMAIL || 'e2e-fresh@example.com',
  password: process.env.E2E_PASSWORD || 'fresh1234',
};

/**
 * Login as parent using demo credentials.
 * @param {import('@playwright/test').Page} page
 */
async function loginAsParent(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', DEMO_USER.email);
  await page.fill('input[name="password"]', DEMO_USER.password);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard', { timeout: 10000 });
}

module.exports = {
  loginAsParent,
};
