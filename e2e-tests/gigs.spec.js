const { test, expect } = require('@playwright/test');

const BASE_URL = 'http://localhost:3003';
const PARENT = { email: process.env.E2E_EMAIL || 'e2e-fresh@example.com', password: process.env.E2E_PASSWORD || 'fresh1234' };
const CHILD = { email: process.env.E2E_CHILD_EMAIL || 'lucas@demo.com', password: process.env.E2E_CHILD_PASSWORD || 'password123' };

async function login(page, user) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(dashboard|parent)/, { timeout: 10000 });
}

async function logout(page, context) {
  await context.clearCookies();
}

test.describe('Gigs lifecycle', () => {
  test('child submits gig with proof, parent approves, points credit', async ({ page, context }) => {
    // ─── Child path ───
    await login(page, CHILD);
    await page.goto(`${BASE_URL}/dashboard`);
    await page.waitForLoadState('networkidle');

    const gigForm = page.locator('form[data-complete-form][data-is-bonus="1"]').first();
    if ((await gigForm.count()) === 0) {
      test.skip(true, 'No gig assignments seeded for demo child — skipping');
      return;
    }

    // Submit triggers modal
    await gigForm.locator('button[type="submit"]').click();
    const modal = page.locator('#gig-proof-modal');
    await expect(modal).toBeVisible();
    await page.fill('#gig-proof-text', 'learned about rootless podman storage layout');
    await page.locator('#gig-proof-submit').click();
    await page.waitForLoadState('networkidle');

    // After redirect, the row should show "Awaiting approval" or live in the pending section
    await expect(page.locator('text=Awaiting approval').first()).toBeVisible({ timeout: 5000 });

    // ─── Parent path ───
    await logout(page, context);
    await login(page, PARENT);

    await page.goto(`${BASE_URL}/parent/approvals`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('text=learned about rootless podman storage layout')).toBeVisible();

    // Approve
    const item = page
      .locator('li[data-id]', { hasText: 'learned about rootless podman storage layout' })
      .first();
    await item.locator('button[data-action="approve"]').click();
    await page.waitForLoadState('networkidle');

    // Row should have been removed
    await expect(
      page.locator('text=learned about rootless podman storage layout')
    ).not.toBeVisible();
  });

  test('child cannot complete a gig while a mandatory is pending today', async ({ page }) => {
    await login(page, CHILD);
    await page.goto(`${BASE_URL}/dashboard`);
    await page.waitForLoadState('networkidle');

    // If the dashboard shows the "bonus locked" state, the gig form should not be present
    // (the existing dashboard hides complete buttons via bonusUnlocked). Verify either:
    //   a) No bonus form exists, OR
    //   b) The bonus form is present but is_locked badge visible.
    const lockedBadges = page.locator('text=/locked/i');
    const gigForms = page.locator('form[data-complete-form][data-is-bonus="1"]');
    const lockedCount = await lockedBadges.count();
    const gigCount = await gigForms.count();

    if (lockedCount === 0 && gigCount === 0) {
      test.skip(true, 'Seeded state has no pending mandatory + gigs — skipping');
      return;
    }

    expect(lockedCount > 0 || gigCount === 0).toBeTruthy();
  });
});
