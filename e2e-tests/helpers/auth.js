const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const DEMO_USER = {
  email: process.env.E2E_EMAIL || 'e2e-fresh@example.com',
  password: process.env.E2E_PASSWORD || 'fresh1234',
};

/**
 * Login as parent using demo credentials.
 *
 * Robust against the login page's two known footguns:
 *  1. The submit handler binds on `astro:page-load` (≈DOMContentLoaded), so we
 *     wait for networkidle before submitting — otherwise the click fires a
 *     native form submit before the handler exists and login never runs,
 *     leaving us stranded on /login until waitForURL times out.
 *  2. The page has a second `type=submit` (the language toggle), so we click
 *     the login button by id (`#login-submit-btn`), not an ambiguous selector.
 * The generous waitForURL budget covers the check-methods + login round-trips
 * plus the dashboard SSR render.
 *
 * @param {import('@playwright/test').Page} page
 */
async function loginAsParent(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', DEMO_USER.email);
  await page.fill('input[name="password"]', DEMO_USER.password);
  await page.click('#login-submit-btn');
  await page.waitForURL(/\/(dashboard|parent)$/, { timeout: 30000 });
}

module.exports = {
  BASE_URL,
  DEMO_USER,
  loginAsParent,
};
