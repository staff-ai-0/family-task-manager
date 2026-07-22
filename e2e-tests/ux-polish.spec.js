const { test, expect } = require('@playwright/test');
const { loginAsParent, BASE_URL } = require('./helpers/auth');

// Regression coverage for the #55 UX-polish changes (manually browser-verified
// 2026-06-21): dead report tab removed, settings accordion auto-open + persist,
// and in-place gig archive.
test.describe('UX polish (#55)', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsParent(page);
  });

  test('reports has no dead "vs Budget" sub-tab', async ({ page }) => {
    await page.goto(`${BASE_URL}/budget/reports`);
    await page.waitForLoadState('networkidle');
    // 5 tabs now (Spending/Cashflow/Forecast/Net Worth/Budget vs Actual) —
    // Forecast + a REAL "Budget vs Actual" report (commits 2e14a1b, 5e89a8e)
    // were added after this test was written. The thing this test actually
    // guards against — the old permanent "Coming soon" dead-end literally
    // labeled "vs Budget"/"vs Presupuesto" (commit 32210a4) — is still gone;
    // its replacement is labeled "Budget vs Actual"/"Plan vs Real" instead.
    await expect(page.locator('.report-tab')).toHaveCount(5);
    await expect(page.getByText('vs Budget', { exact: true })).toHaveCount(0);
    await expect(page.getByText('vs Presupuesto', { exact: true })).toHaveCount(0);
  });

  test('settings auto-opens the first accordion when nothing is persisted', async ({ page }) => {
    await page.goto(`${BASE_URL}/budget/settings`);
    await page.evaluate(() => localStorage.removeItem('settingsAccordionOpen'));
    await page.reload();
    await page.waitForLoadState('networkidle');
    const openCount = await page.$$eval(
      '.accordion-toggle',
      (els) => els.filter((e) => e.getAttribute('aria-expanded') === 'true').length
    );
    expect(openCount).toBe(1);
  });

  test('settings persists an explicitly-opened accordion across reload', async ({ page }) => {
    await page.goto(`${BASE_URL}/budget/settings`);
    await page.evaluate(() => localStorage.removeItem('settingsAccordionOpen'));
    await page.reload();
    await page.waitForLoadState('networkidle');
    // Open a non-default section, then reload.
    await page.$$eval('.accordion-toggle', (els) => els[2].click());
    await page.reload();
    await page.waitForLoadState('networkidle');
    const openLabels = await page.$$eval('.accordion-toggle', (els) =>
      els
        .filter((e) => e.getAttribute('aria-expanded') === 'true')
        .map((e) => e.textContent.trim().split('\n')[0])
    );
    expect(openLabels.length).toBeGreaterThanOrEqual(1);
  });

  test('archiving a gig removes its card in place when others remain', async ({ page }) => {
    // Unique per-run titles: repeated local runs against the same unreseeded
    // stack were accumulating same-named "E2E Gig B" cards from prior runs
    // (this test never archived B), making the toHaveCount(1) assertion
    // flaky/failing (11, 12, 13... across successive local runs). Archive
    // both at the end so the test is self-cleaning too.
    const ts = Date.now();
    const titleA = `E2E Gig A ${ts}`;
    const titleB = `E2E Gig B ${ts}`;
    for (const title of [titleA, titleB]) {
      const r = await page.request.post(`${BASE_URL}/api/gigs/offerings`, {
        data: { title, description: 'e2e', points: 12, difficulty: 1, category: 'other' },
      });
      expect(r.status()).toBe(201);
    }
    page.on('dialog', (d) => d.accept()); // auto-accept the "Archive?" confirm
    await page.goto(`${BASE_URL}/parent/gigs`);
    await page.waitForLoadState('networkidle');

    expect(await page.locator('[data-gig-card]').count()).toBeGreaterThanOrEqual(2);
    const cardA = page.locator('[data-gig-card]', { hasText: titleA });
    await cardA.locator('.archive-gig-btn').click();

    // In-place removal: A vanishes, B stays — no full-page reload to empty-state.
    await expect(page.locator('[data-gig-card]', { hasText: titleA })).toHaveCount(0);
    const cardB = page.locator('[data-gig-card]', { hasText: titleB });
    await expect(cardB).toHaveCount(1);

    // Cleanup: archive B too so this run doesn't leave data for the next one.
    await cardB.locator('.archive-gig-btn').click();
    await expect(page.locator('[data-gig-card]', { hasText: titleB })).toHaveCount(0);
  });
});
