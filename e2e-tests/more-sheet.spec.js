const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';

// WK29 QA (Jesus): on desktop widths the "Más" sheet could only be closed via
// the X. Cause: the sheet wrapper is fixed full-width (z-60) while the inner
// card is max-w-md centered — clicks BESIDE the card land on the transparent
// wrapper, never reaching the backdrop (z-55) whose click handler closes.
async function openMoreSheet(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', 'mom@demo.com');
  await page.fill('input[name="password"]', 'password123');
  await page.click('#login-submit-btn');
  await page.waitForURL('**/dashboard', { timeout: 30000 });
  // The driver.js welcome tour auto-starts in a fresh context and its overlay
  // would intercept clicks — dismiss it if present before opening the sheet.
  const tourClose = page.locator('.driver-popover-close-btn');
  if (await tourClose.isVisible({ timeout: 2000 }).catch(() => false)) {
    await tourClose.click();
    await expect(page.locator('.driver-popover')).toHaveCount(0);
  }
  await page.click('#more-nav-btn');
  await expect(page.locator('#more-sheet')).not.toHaveAttribute('aria-hidden', 'true');
  // Let the 300ms slide-up transition finish — clicking mid-animation hits
  // the backdrop (sheet still low) and false-passes the dead-zone test.
  await page.waitForTimeout(400);
}

test.describe('More sheet outside-click close', () => {
  test('click beside the card (desktop dead zone) closes the sheet', async ({ page }) => {
    await openMoreSheet(page);
    // Left band at sheet height: inside the full-width wrapper, outside the
    // centered max-w-md card (card spans ~[416,864] at 1280px viewport).
    await page.mouse.click(150, 600);
    await expect(page.locator('#more-sheet')).toHaveAttribute('aria-hidden', 'true', { timeout: 2000 });
  });

  test('click on the dimmed backdrop above the sheet closes it', async ({ page }) => {
    await openMoreSheet(page);
    await page.mouse.click(640, 60);
    await expect(page.locator('#more-sheet')).toHaveAttribute('aria-hidden', 'true', { timeout: 2000 });
  });

  test('X button still closes', async ({ page }) => {
    await openMoreSheet(page);
    await page.click('#more-close');
    await expect(page.locator('#more-sheet')).toHaveAttribute('aria-hidden', 'true', { timeout: 2000 });
  });
});
