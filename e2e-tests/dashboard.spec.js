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
  await page.waitForURL(/\/(dashboard|parent)$/, { timeout: 30000 });
}

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  // ── Page load ──────────────────────────────────────────────────────────
  // The e2e account is a PARENT: since the /dashboard→/parent merge
  // (spec 2026-07-24) they land on the parent hub. Layout tests below
  // (nav, More sheet, lang toggle) are role-agnostic and run there.

  test('parent hitting /dashboard is redirected to /parent', async ({ page }) => {
    await page.goto(`${BASE_URL}/dashboard`);
    await page.waitForURL('**/parent', { timeout: 10000 });
    await expect(page).toHaveURL(/\/parent$/);
  });

  test('parent /dashboard redirect preserves module_off banner', async ({ page }) => {
    await page.goto(`${BASE_URL}/dashboard?module_off=1`);
    await page.waitForURL(/\/parent\?module_off=1/, { timeout: 10000 });
    await expect(page.locator('body')).toContainText(/desactivada|switched off/i);
  });

  test('renders parent hub header', async ({ page }) => {
    await expect(page.locator('header h1')).toBeVisible({ timeout: 5000 });
  });

  // ── Bottom navigation ──────────────────────────────────────────────────

  test('bottom nav is 5 items + a More sheet with secondary destinations', async ({ page }) => {
    // Role-agnostic: the 5th item is always the More button, and the More
    // sheet holds the secondary destinations (notifications, profile, chat)
    // for both kid and parent navs.
    const nav = page.locator('nav');
    await expect(nav).toBeVisible();
    await expect(nav.locator('#more-nav-btn')).toBeVisible();

    await nav.locator('#more-nav-btn').click();
    const sheet = page.locator('#more-sheet');
    await expect(sheet.locator('a[href="/notifications"]')).toBeVisible();
    await expect(sheet.locator('a[href="/profile"]')).toBeVisible();
    await expect(sheet.locator('a[href="/chat"]')).toBeVisible();
  });

  test('chat is reachable via the More sheet', async ({ page }) => {
    await page.locator('nav #more-nav-btn').click();
    await page.locator('#more-sheet a[href="/chat"]').click();
    await page.waitForURL('**/chat', { timeout: 8000 });
    await expect(page).toHaveURL(/\/chat$/);
  });

  test('notifications reachable via the More sheet', async ({ page }) => {
    await page.locator('nav #more-nav-btn').click();
    await page.locator('#more-sheet a[href="/notifications"]').click();
    await page.waitForURL('**/notifications', { timeout: 8000 });
    await expect(page).toHaveURL(/\/notifications$/);
  });

  test('nav (and its More button) persists after client-side navigation', async ({ page }) => {
    // Open a secondary page from the More sheet, then confirm the 5-item nav
    // (incl. the More button) is still present.
    await page.locator('nav #more-nav-btn').click();
    await page.locator('#more-sheet a[href="/profile"]').click();
    await page.waitForURL('**/profile', { timeout: 8000 });
    await expect(page.locator('nav #more-nav-btn')).toBeVisible({ timeout: 5000 });
  });

  // ── Language toggle ────────────────────────────────────────────────────

  test('language toggle in the More sheet flips the lang cookie', async ({ page }) => {
    const langBefore = (await page.context().cookies())
      .find((c) => c.name === 'lang')?.value ?? 'en';

    // The language toggle now lives in the More sheet (not a top nav slot).
    await page.locator('nav #more-nav-btn').click();
    const langForm = page.locator('#more-sheet form[action="/api/lang"]');
    await expect(langForm).toBeVisible();
    await langForm.locator('button').click();
    await page.waitForLoadState('networkidle');

    const langAfter = (await page.context().cookies())
      .find((c) => c.name === 'lang')?.value;
    expect(langAfter).toBeTruthy();
    expect(langAfter).not.toBe(langBefore);

    // Restore: /api/lang persists preferred_lang on the USER record (not just
    // this cookie), and this test runs against the shared e2e-fresh account —
    // leaving it flipped bleeds into every other spec file that logs in as
    // e2e-fresh and runs alphabetically after this one (found failing
    // members.spec.js and others with English-only text assertions). Restore
    // via a direct API call, not another UI click — the welcome-tour overlay
    // can intercept a second nav click right after this reload.
    await page.request.post('/api/lang', { form: { lang: langBefore } });
  });

  // ── Responsive / visual ────────────────────────────────────────────────

  test('nav is fixed at bottom of viewport', async ({ page }) => {
    const navBox = await page.locator('nav').boundingBox();
    const viewport = page.viewportSize();
    expect(navBox).not.toBeNull();
    // Nav bottom edge should be at or near viewport bottom
    expect(navBox.y + navBox.height).toBeGreaterThan(viewport.height - 80);
  });
});
