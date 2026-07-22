const { test, expect } = require('@playwright/test');

/**
 * Kid-side onboarding coverage:
 *  - the kid welcome tour auto-starts on /dashboard, is skippable, and stays
 *    dismissed after a reload (the onDestroyStarted/sendBeacon persistence fix);
 *  - the dashboard is kid-gated (the isKid-only push-enable button renders for a
 *    child — guards the lowercase-role fix in PR #60);
 *  - a kid sees their cash-from-gigs balance card on the dashboard.
 *
 * Requires the dev stack on :3003 with the current build + seeded demo data.
 */
test.describe('Kid onboarding', () => {
  const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
  const PASS = 'KidOnb123!';

  test('kid tour auto-starts, is skippable, persists; dashboard is kid-gated', async ({ page, context }) => {
    const ts = Date.now();
    const parentEmail = `kid-onb-parent-${ts}@example.com`;
    const kidEmail = `kid-onb-kid-${ts}@example.com`;

    // Register a fresh family (creates a PARENT).
    await page.goto(`${BASE_URL}/register`);
    await page.waitForLoadState('networkidle');
    await page.fill('input[name="family_name"]', `KidOnb ${ts}`);
    await page.fill('input[name="name"]', 'Onb Parent');
    await page.fill('input[name="email"]', parentEmail);
    await page.fill('input[name="password"]', PASS);
    await page.fill('input[name="password_confirm"]', PASS);
    await page.check('#accept_terms');
    await page.click('#register-submit-btn');
    await page.waitForURL(/\/(dashboard|parent)/, { timeout: 30000 });

    // Create a child login via the members "Register Member" form.
    await page.goto(`${BASE_URL}/parent/members`);
    await page.waitForLoadState('networkidle');
    const form = page.locator('form:has(input[name="password"])');
    await form.locator('input[name="name"]').fill('Onb Kid');
    await form.locator('input[name="email"]').fill(kidEmail);
    await form.locator('input[name="password"]').fill(PASS);
    await form.locator('select[name="role"]').selectOption('child');
    await page.click('button:has-text("Register Member")');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText('Onb Kid');

    // Log out, log in as the child.
    await context.clearCookies();
    await page.goto(`${BASE_URL}/login`);
    await page.fill('input[name="email"]', kidEmail);
    await page.fill('input[name="password"]', PASS);
    await page.click('#login-submit-btn');
    await page.waitForURL('**/dashboard', { timeout: 30000 });

    // Kid welcome tour auto-starts.
    const popover = page.locator('.driver-popover');
    await expect(popover).toBeVisible({ timeout: 10000 });
    await expect(page.locator('.driver-popover-title')).toHaveText(/Welcome/i);

    // Kid-gating: the push-enable button is rendered only inside {isKid && ...}.
    await expect(page.locator('#enable-push-btn')).toHaveCount(1);

    // Skip, then confirm it does not return after an immediate reload.
    await page.locator('.driver-popover-close-btn').click();
    await expect(popover).toBeHidden({ timeout: 5000 });
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);
    await expect(page.locator('.driver-popover')).toHaveCount(0);
  });

  test('kid dashboard shows the cash-from-gigs balance card', async ({ page }) => {
    // The self-serve "convert points to money" flow was intentionally removed
    // 2026-06-30 (commit 30d83c6, "removed dead PointsConverter") — the
    // two-currency economy now pays gig-board cash via /parent/payouts and
    // Family Bank allowance, not a kid-initiated points conversion. Points
    // stay a separate privileges currency (see CLAUDE.md's two-currency
    // economy section). This asserts the replacement: the kid dashboard's
    // cash-balance card.
    await page.goto(`${BASE_URL}/login`);
    await page.fill('input[name="email"]', 'emma@demo.com');
    await page.fill('input[name="password"]', 'password123');
    await page.click('#login-submit-btn');
    await page.waitForURL('**/dashboard', { timeout: 30000 });

    // Dismiss the welcome tour if it shows (emma's first visit).
    const close = page.locator('.driver-popover-close-btn');
    if (await close.isVisible().catch(() => false)) {
      await close.click();
      await page.waitForTimeout(300);
    }

    await expect(page.locator('[data-cash-badge]')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('[data-cash-badge]')).toContainText(/MXN/);
  });
});
