const { test, expect } = require('@playwright/test');

/**
 * Welcome tour smoke test.
 *
 * Registers a brand-new family (so `completed_welcome_tour` is false), confirms
 * the driver.js tour auto-starts on the landing page, skips it, and verifies it
 * does NOT re-appear after a reload (localStorage guard + backend ack-tour flag).
 *
 * Requires the dev stack up on :3003 with a frontend build that includes the
 * tour work (rebuild the frontend container after pulling these changes).
 */
test.describe('Welcome tour', () => {
  const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';

  const NEW_USER = {
    familyName: `Tour-${Date.now()}`,
    name: 'Tour Parent',
    email: `tour-${Date.now()}@demo.com`,
    password: 'TourPass123!',
  };

  test('auto-starts for a new family, is skippable, and does not re-show', async ({ page }) => {
    // Register a new family — this creates a PARENT and lands on /dashboard.
    await page.goto(`${BASE_URL}/register`);
    await page.waitForLoadState('networkidle');

    await page.fill('input[name="family_name"]', NEW_USER.familyName);
    await page.fill('input[name="name"]', NEW_USER.name);
    await page.fill('input[name="email"]', NEW_USER.email);
    await page.fill('input[name="password"]', NEW_USER.password);
    await page.fill('input[name="password_confirm"]', NEW_USER.password);
    await page.click('#register-submit-btn');
    await page.waitForURL(/\/(dashboard|parent)/, { timeout: 30000 });

    // The PARENT setup tour fires on /parent (where the checklist it highlights
    // lives); a freshly-registered parent reaches it via Manage.
    await page.goto(`${BASE_URL}/parent`);
    await page.waitForLoadState('networkidle');

    const popover = page.locator('.driver-popover');
    await expect(popover).toBeVisible({ timeout: 10000 });

    // Skip the tour via the close button.
    await page.locator('.driver-popover-close-btn').click();
    await expect(popover).toBeHidden({ timeout: 5000 });

    // Reload — the tour must NOT re-appear (persisted completion).
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500); // past the 450ms auto-start delay
    await expect(page.locator('.driver-popover')).toHaveCount(0);
  });
});
