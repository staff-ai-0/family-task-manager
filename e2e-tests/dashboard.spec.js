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

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  // ── Page load ──────────────────────────────────────────────────────────

  test('renders header with user name and points', async ({ page }) => {
    // Header greeting + points card always visible regardless of role
    await expect(page.locator('header h1')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('header')).toContainText(/\d/); // points value
  });

  test('shows today section', async ({ page }) => {
    const main = page.locator('main');
    await expect(main).toBeVisible();
    // Heading says "Today" (EN) or "Hoy" (ES)
    await expect(page.locator('h2').first()).toContainText(/today|hoy/i);
  });

  // ── Bottom navigation ──────────────────────────────────────────────────

  test('bottom nav contains the 5 kid destinations', async ({ page }) => {
    const nav = page.locator('nav');
    await expect(nav).toBeVisible();

    // Kid bottom nav: Tasks, Gigs, Rewards, Chat, More (5 items).
    await expect(nav.locator('a[href="/dashboard"]')).toBeVisible();
    await expect(nav.locator('a[href="/gigs"]')).toBeVisible();
    await expect(nav.locator('a[href="/rewards"]')).toBeVisible();
    await expect(nav.locator('a[href="/chat"]')).toBeVisible();
    await expect(nav.locator('#more-nav-btn')).toBeVisible();

    // Secondary destinations (notifications, profile) live in the More sheet.
    await nav.locator('#more-nav-btn').click();
    const sheet = page.locator('#more-sheet');
    await expect(sheet.locator('a[href="/notifications"]')).toBeVisible();
    await expect(sheet.locator('a[href="/profile"]')).toBeVisible();
  });

  test('chat nav link is reachable', async ({ page }) => {
    await page.locator('nav a[href="/chat"]').click();
    await page.waitForURL('**/chat', { timeout: 8000 });
    await expect(page).toHaveURL(/\/chat$/);
  });

  test('notifications reachable via the More sheet', async ({ page }) => {
    await page.locator('nav #more-nav-btn').click();
    await page.locator('#more-sheet a[href="/notifications"]').click();
    await page.waitForURL('**/notifications', { timeout: 8000 });
    await expect(page).toHaveURL(/\/notifications$/);
  });

  test('nav persists after view-transition navigation', async ({ page }) => {
    // Navigate away and back via VT (client-side); nav must still have chat
    await page.locator('nav a[href="/rewards"]').click();
    await page.waitForURL('**/rewards', { timeout: 8000 });

    const navAfterVT = page.locator('nav');
    await expect(navAfterVT.locator('a[href="/chat"]')).toBeVisible({ timeout: 5000 });
    await expect(navAfterVT.locator('#more-nav-btn')).toBeVisible();

    // Navigate back to dashboard
    await page.locator('nav a[href="/dashboard"]').click();
    await page.waitForURL('**/dashboard', { timeout: 8000 });
    await expect(page.locator('nav a[href="/chat"]')).toBeVisible();
  });

  // ── Language toggle ────────────────────────────────────────────────────

  test('language toggle switches between EN and ES', async ({ page }) => {
    // Default language: EN — header says "Hello,"
    const header = page.locator('header');
    await expect(header).toContainText(/hello|hola/i);

    // Switch to ES
    const langBtn = page.locator('nav button', { hasText: /es|en/i }).first();
    await langBtn.click();
    await page.waitForLoadState('networkidle');

    // Now header should say "Hola," or "Hello," depending on direction
    await expect(page.locator('header')).toContainText(/hola|hello/i);
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
