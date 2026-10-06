const { test, expect } = require('@playwright/test');
const { BASE_URL, CHILD_USER, loginAs, loginAsParent } = require('./helpers/auth');

/**
 * Family Bank — the money UI that had no e2e coverage at all.
 *
 * Two surfaces, two roles:
 *  - /bank is the KID surface (three jars + goal + move-money actions). A parent
 *    who lands there is 301'd to /parent/settings/family-bank, so these tests
 *    need E2E_CHILD_EMAIL to be an actual CHILD/TEEN.
 *  - /parent/payouts is where a parent settles up: gig cash payouts and the
 *    per-week chore-paycheck release.
 *
 * Both paths live under the `gigs` module (frontend/src/middleware.ts —
 * moduleForPath), so a family with that module switched off is bounced to
 * /dashboard?module_off=1; that is a skip, not a failure.
 */

/** True when the middleware bounced us out of a switched-off module. */
function bouncedByModuleGate(page) {
  return page.url().includes('module_off=1');
}

test.describe('Family Bank — kid jars', () => {
  test.beforeEach(async ({ page }) => {
    const loggedIn = await loginAs(page, CHILD_USER).then(() => true).catch(() => false);
    test.skip(
      !loggedIn,
      `could not log in as ${CHILD_USER.email} — set E2E_CHILD_EMAIL / E2E_CHILD_PASSWORD to a kid in this environment`
    );
    await page.goto(`${BASE_URL}/bank`);
    await page.waitForLoadState('networkidle');
    test.skip(
      page.url().includes('/parent/settings/family-bank'),
      `${CHILD_USER.email} is a PARENT — /bank is the kid surface`
    );
    test.skip(bouncedByModuleGate(page), 'the gigs module (which carries /bank) is off for this family');
  });

  test('kid balance renders: total plus the three jars', async ({ page }) => {
    // The header total is "$X.XX MXN"; each jar is exactly "$X.XX". A failed
    // /api/bank/me render would show the red "Could not load your bank" banner
    // and zeroed jars, so assert the banner is absent too.
    await expect(page.getByText(/Could not load your bank|No pudimos cargar tu banco/)).toHaveCount(0);
    await expect(page.locator('[data-total-balance]')).toContainText(/^\$-?\d+\.\d{2}/);

    for (const jar of ['spend', 'save', 'share']) {
      await expect(page.locator(`[data-jar-balance="${jar}"]`)).toHaveText(/^\$-?\d+\.\d{2}$/);
    }

    // What is on screen must be what the API said. Cross-checked against
    // /api/bank/me rather than summing the jars: total_cents is the kid's
    // authoritative cash balance (users.cash_cents), not a derived jar sum.
    const cents = async (sel) =>
      Math.round(parseFloat((await page.locator(sel).innerText()).replace(/[^0-9.-]/g, '')) * 100);
    const me = await (await page.request.get(`${BASE_URL}/api/bank/me`)).json();
    expect(await cents('[data-total-balance]')).toBe(me.total_cents);
    expect(await cents('[data-jar-balance="spend"]')).toBe(me.spend_cents);
    expect(await cents('[data-jar-balance="save"]')).toBe(me.save_cents);
    expect(await cents('[data-jar-balance="share"]')).toBe(me.share_cents);
  });

  test('a move-money action opens the amount modal', async ({ page }) => {
    // Read-only: opens the dialog and closes it, no transfer is posted.
    await page.locator('[data-bank-action="spend-save"]').click();
    const modal = page.locator('#bank-modal');
    await expect(modal).toBeVisible();
    await expect(page.locator('#bank-modal-title')).toContainText(/Ahorrar|Save/);
    await expect(page.locator('#bank-modal-amount')).toBeFocused();
    await page.locator('#bank-modal-close').click();
    await expect(modal).toBeHidden();
  });
});

test.describe('Family Bank — parent payouts', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsParent(page);
    await page.goto(`${BASE_URL}/parent/payouts`);
    await page.waitForLoadState('networkidle');
    test.skip(bouncedByModuleGate(page), 'the gigs module (which carries /parent/payouts) is off for this family');
  });

  test('payouts page totals what is owed to the kids', async ({ page }) => {
    const header = page.locator('[data-owed-header]');
    await expect(header).toBeVisible();
    await expect(header.locator('[data-grand-total]')).toHaveText(/^\$-?\d+\.\d{2}$/);
    // Grand total = gig cash + outstanding chore paychecks.
    const cents = async (sel) =>
      Math.round(parseFloat((await header.locator(sel).innerText()).replace(/[^0-9.-]/g, '')) * 100);
    expect(await cents('[data-grand-total]')).toBe(
      (await cents('[data-cash-total]')) + (await cents('[data-paycheck-total]'))
    );
  });

  test('parent pays the week by uploading a transfer receipt', async ({ page }) => {
    // The per-week Release / Adj / Top-up controls are gone: the parent uploads
    // the bank receipt and the app records it. Scan + confirm are mocked — this
    // checks the flow, not Gemini.
    await expect(page.locator('[data-upload-receipts]')).toBeVisible();
    await page.locator('[data-upload-receipts]').click();
    await expect(page).toHaveURL(/\/parent\/payouts\/receipts/);

    const kidId = '00000000-0000-0000-0000-0000000000aa';
    await page.route('**/api/bank/payout-receipts/scan', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          receipts: [{
            filename: 'slip.png', readable: true, folio: '0011968514', receipt_date: '2026-09-04',
            concept: 'semana 36', amount_cents: 25000, beneficiary: 'Ariana Michelle M', user_id: kidId,
            duplicate_folio: false, weeks_from_concept: true, mismatch: false,
            allocations: [{ week_of: '2026-08-31', amount_cents: 25000, already_paid: false, projected_cents: 25000 }],
          }],
        }),
      })
    );
    let confirmed = null;
    await page.route('**/api/bank/payout-receipts/confirm', (route) => {
      confirmed = route.request().postDataJSON();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ folio: '0011968514', user_id: kidId, amount_cents: 25000, weeks: [] }),
      });
    });

    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
    await page.setInputFiles('#receipt-files', { name: 'slip.png', mimeType: 'image/png', buffer: png });
    await expect(page.locator('[data-row-key]')).toHaveCount(1);
    await expect(page.locator('#record-btn')).toBeEnabled();
    await page.locator('#record-btn').click();
    await expect(page.locator('#done-box')).toBeVisible();
    expect(confirmed).toMatchObject({ folio: '0011968514', user_id: kidId, amount_cents: 25000 });
  });
});
