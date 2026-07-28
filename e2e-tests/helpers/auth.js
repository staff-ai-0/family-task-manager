const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const DEMO_USER = {
  email: process.env.E2E_EMAIL || 'e2e-fresh@example.com',
  password: process.env.E2E_PASSWORD || 'fresh1234',
};
// Default matches the documented one in README.md (seed_data.py demo child).
const CHILD_USER = {
  email: process.env.E2E_CHILD_EMAIL || 'emma@demo.com',
  password: process.env.E2E_CHILD_PASSWORD || 'password123',
};
// Platform operator for the /admin console. Deliberately has NO default:
// require_superadmin (backend/app/core/dependencies.py) needs BOTH
// users.is_superadmin AND membership of SUPERADMIN_EMAILS, and answers 404 when
// either is missing — a guessed default would only produce 404s that look like
// a broken console. admin.spec.js skips its operator tests when this is unset.
const OPERATOR_USER = {
  email: process.env.E2E_ADMIN_EMAIL || '',
  password: process.env.E2E_ADMIN_PASSWORD || '',
};

/**
 * Log in as an arbitrary account.
 *
 * Robust against the login page's two known footguns:
 *  1. The submit handler binds on `astro:page-load` (≈DOMContentLoaded), so we
 *     wait for networkidle before submitting — otherwise the click fires a
 *     native form submit before the handler exists and login never runs,
 *     leaving us stranded on /login until waitForURL times out.
 *  2. The page has a second `type=submit` (the language toggle), so we click
 *     the login button by id (`#login-submit-btn`), not an ambiguous selector.
 * The generous waitForURL budget covers the check-methods + login round-trips
 * plus the dashboard SSR render. Parents land on /parent, kids on /dashboard.
 *
 * @param {import('@playwright/test').Page} page
 * @param {{email: string, password: string}} user
 */
async function loginAs(page, user) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);
  await page.click('#login-submit-btn');
  await page.waitForURL(/\/(dashboard|parent)$/, { timeout: 30000 });
}

/**
 * Login as parent using demo credentials.
 *
 * @param {import('@playwright/test').Page} page
 */
async function loginAsParent(page) {
  await loginAs(page, DEMO_USER);
}

module.exports = {
  BASE_URL,
  DEMO_USER,
  CHILD_USER,
  OPERATOR_USER,
  loginAs,
  loginAsParent,
};
