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

  test('parent releases an outstanding chore paycheck week', async ({ page }) => {
    // Only kids on a chore-based allowance mode have outstanding weeks; on flat
    // mode outstanding_weeks is empty by construction (schemas/bank.py).
    const summaryRes = await page.request.get(`${BASE_URL}/api/bank/payout-summary`);
    test.skip(!summaryRes.ok(), `payout summary unavailable (HTTP ${summaryRes.status()})`);
    const summary = await summaryRes.json();
    const kid = (summary.kids ?? []).find((k) =>
      (k.outstanding_weeks ?? []).some((w) => !w.already_released)
    );
    test.skip(
      !kid,
      'no kid has an unreleased chore-paycheck week (every kid is on flat allowance, or every week is already released)'
    );
    const week = kid.outstanding_weeks.find((w) => !w.already_released);

    const rowSel = `[data-paycheck-row][data-kid-id="${kid.user_id}"][data-week-of="${week.week_of}"]`;
    await expect(page.locator(rowSel)).toHaveCount(1);

    const posted = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/bank/chore-paycheck/${kid.user_id}/release`) &&
        r.request().method() === 'POST'
    );
    await page.locator(`${rowSel} [data-release]`).click();
    const res = await posted;
    // Releasing is premium-gated (family_bank_automation → Plus). A free-tier
    // family gets 403 upgrade_required; that is an entitlement fact about the
    // environment, not a broken release flow.
    test.skip(res.status() === 403, 'Family Bank automation requires a Plus plan on this family');
    expect(res.ok()).toBeTruthy();

    // Either way the release control is gone: the CURRENT week's row stays and
    // flips to "Released ✓", a PAST week's row is dropped (parent/payouts.astro).
    await expect(page.locator(`${rowSel} [data-release]`)).toHaveCount(0);
    if (week.is_current_week) {
      await expect(page.locator(`${rowSel} [data-release-slot]`)).toContainText(/Liberado|Released/);
    } else {
      await expect(page.locator(rowSel)).toHaveCount(0);
    }

    // Server-side truth, not just the optimistic DOM update: the week must come
    // back released (release is idempotent per kid+week).
    const after = await (await page.request.get(`${BASE_URL}/api/bank/payout-summary`)).json();
    const kidAfter = (after.kids ?? []).find((k) => k.user_id === kid.user_id);
    const weekAfter = (kidAfter?.outstanding_weeks ?? []).find((w) => w.week_of === week.week_of);
    expect(weekAfter === undefined || weekAfter.already_released).toBeTruthy();
  });
});
