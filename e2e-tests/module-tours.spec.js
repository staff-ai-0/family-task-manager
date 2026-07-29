const { test, expect } = require('@playwright/test');
const { loginAsParent, BASE_URL } = require('./helpers/auth');

// driver.js renders its popover into .driver-popover.
const POPOVER = '.driver-popover';

/** Clear the per-tour localStorage guard so a run starts from a clean slate. */
async function clearLocalGuards(page) {
  await page.evaluate(() => {
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith('ftm_tour_')) localStorage.removeItem(k);
    }
  });
}

test.describe('Per-module tours', () => {
  test('a brand-new parent gets the budget tour once, then never again', async ({ page }) => {
    // A genuinely new account, because the point under test is what happens on
    // a FIRST visit — the shared e2e parent has already been through this by
    // the time the suite has run once, which would make the assertion lie.
    const stamp = `${process.pid}-${test.info().workerIndex}-${Date.now()}`;
    const reg = await page.request.post(`${BASE_URL}/api/auth/register`, {
      data: {
        family_name: `Tour Test ${stamp}`,
        name: 'Tour Parent',
        email: `tour-${stamp}@example.com`,
        password: 'tourtest1234',
        role: 'parent',
        accept_terms: true,
      },
    });
    expect(reg.ok()).toBeTruthy();

    await page.goto(`${BASE_URL}/budget`);
    await clearLocalGuards(page);
    await page.reload();

    // First visit: it runs, and it opens on the step that frames the module.
    await expect(page.locator(POPOVER)).toBeVisible({ timeout: 6000 });
    await expect(page.locator(POPOVER)).toContainText(
      /Your family budget|El presupuesto familiar/i,
    );

    // Finish it the way a user would, then come back.
    await page.keyboard.press('Escape');
    await expect(page.locator(POPOVER)).toHaveCount(0);
    await page.waitForTimeout(500);

    await page.goto(`${BASE_URL}/budget`);
    await page.waitForTimeout(1500);
    await expect(page.locator(POPOVER)).toHaveCount(0);
  });

  test('a tour already completed does not run again', async ({ page }) => {
    await loginAsParent(page);
    await page.goto(`${BASE_URL}/budget`);
    await clearLocalGuards(page);
    await page.request.post(`${BASE_URL}/api/onboarding/tours/budget-parent/complete`);

    // Server-side flag alone must be enough — the local guard was just cleared.
    await page.goto(`${BASE_URL}/budget`);
    await page.waitForTimeout(1500);
    await expect(page.locator(POPOVER)).toHaveCount(0);
  });

  test('an explicit replay overrides both guards', async ({ page }) => {
    await loginAsParent(page);
    // Completed above/previously — ?tour= must still run it.
    await page.goto(`${BASE_URL}/budget?tour=budget-parent`);
    await expect(page.locator(POPOVER)).toBeVisible({ timeout: 5000 });
    // Opening step is a centered modal that frames the module.
    await expect(page.locator(POPOVER)).toContainText(
      /Your family budget|El presupuesto familiar/i,
    );
  });

  test('the tour acks itself when closed, and stays closed', async ({ page }) => {
    await loginAsParent(page);
    await page.goto(`${BASE_URL}/budget?tour=budget-parent`);
    await expect(page.locator(POPOVER)).toBeVisible({ timeout: 5000 });

    await page.keyboard.press('Escape');
    await expect(page.locator(POPOVER)).toHaveCount(0);

    // The ack rides sendBeacon, so give it a moment to land server-side. The
    // hub card is the user-visible read of that state.
    await page.waitForTimeout(500);
    await page.goto(`${BASE_URL}/help`);
    await expect(
      page.locator('.tour-hub a[href*="tour=budget-parent"]'),
    ).toContainText(/Done|Hecha/i);

    await page.goto(`${BASE_URL}/budget`);
    await page.waitForTimeout(1200);
    await expect(page.locator(POPOVER)).toHaveCount(0);
  });

  test('completing a tour is idempotent', async ({ page }) => {
    await loginAsParent(page);
    for (let i = 0; i < 3; i++) {
      const r = await page.request.post(
        `${BASE_URL}/api/onboarding/tours/gigs-parent/complete`,
      );
      expect(r.status()).toBe(204);
    }
    // Acking three times must leave one entry, not three — the hub would
    // otherwise grow a duplicate card per replay.
    await page.goto(`${BASE_URL}/help`);
    await expect(page.locator('.tour-hub a[href*="tour=gigs-parent"]')).toHaveCount(1);
    await expect(
      page.locator('.tour-hub a[href*="tour=gigs-parent"]'),
    ).toContainText(/Done|Hecha/i);
  });

  test('an unknown tour id is rejected', async ({ page }) => {
    await loginAsParent(page);
    const r = await page.request.post(`${BASE_URL}/api/onboarding/tours/nope/complete`);
    expect(r.status()).toBe(422);
  });

  test('the replay hub lists a signed-in parent their own tours', async ({ page }) => {
    await loginAsParent(page);
    await page.goto(`${BASE_URL}/help`);

    const hub = page.locator('.tour-hub');
    await expect(hub).toBeVisible();
    await expect(hub).toContainText(/Interactive guides|Guías interactivas/i);
    // Parent tours only — the kid variants belong to a different reader.
    await expect(hub.locator('a[href*="tour=budget-parent"]')).toHaveCount(1);
    await expect(hub.locator('a[href*="tour=gigs-kid"]')).toHaveCount(0);
  });

  test('a hub card replays its tour', async ({ page }) => {
    await loginAsParent(page);
    await page.goto(`${BASE_URL}/help`);
    await page.locator('.tour-hub a[href*="tour=budget-parent"]').click();
    await page.waitForURL('**/budget?tour=budget-parent');
    await expect(page.locator(POPOVER)).toBeVisible({ timeout: 5000 });
  });

  test('an anonymous reader gets the guide without the hub', async ({ page, context }) => {
    await context.clearCookies();
    await page.goto(`${BASE_URL}/help`);
    await expect(page.locator('.guide')).toBeVisible();
    await expect(page.locator('.tour-hub')).toHaveCount(0);
  });
});
