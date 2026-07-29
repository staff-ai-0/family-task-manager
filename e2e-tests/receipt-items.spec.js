const { test, expect } = require('@playwright/test');
const { loginAsParent, BASE_URL } = require('./helpers/auth');

/**
 * Reading a receipt's line items back after the scan.
 *
 * The scan confirm card was the only place the breakdown was ever rendered.
 * The rows were stored, then orphaned: no endpoint could return the items OF a
 * transaction, no page listed them, and the one page that showed item data
 * (/budget/items/<name>) was reachable only from that same confirm card and
 * linked onward to a route that 404s.
 */

/**
 * Guarantee the family has at least one transaction to open.
 *
 * Without this the interesting tests below skip themselves on a family with an
 * empty ledger — a green run that asserted nothing.
 */
async function ensureTransaction(page) {
  // Must be in the CURRENT month: the transactions page opens on this month,
  // so a ledger full of January rows still renders an empty list.
  const today = new Date().toISOString().slice(0, 10);
  const firstOfMonth = `${today.slice(0, 7)}-01`;
  const existing = await page.request.get(
    `${BASE_URL}/api/budget/transactions/?start_date=${firstOfMonth}&end_date=${today}&limit=1`,
  );
  if (existing.ok() && (await existing.json()).length > 0) return;

  const accountsRes = await page.request.get(`${BASE_URL}/api/budget/accounts/`);
  let accounts = accountsRes.ok() ? await accountsRes.json() : [];
  if (accounts.length === 0) {
    const made = await page.request.post(`${BASE_URL}/api/budget/accounts/`, {
      data: { name: 'E2E Cash', type: 'checking', currency: 'MXN' },
    });
    if (!made.ok()) return;
    accounts = [await made.json()];
  }

  await page.request.post(`${BASE_URL}/api/budget/transactions/`, {
    data: {
      account_id: accounts[0].id,
      date: today,
      amount: -8700,
      notes: 'e2e receipt-items fixture',
    },
  });
}

test.describe('Receipt line items are readable after the scan', () => {
  test('the items endpoint can be scoped to one transaction', async ({ page }) => {
    await loginAsParent(page);
    const list = await page.request.get(`${BASE_URL}/api/budget/transactions/?limit=1`);
    expect(list.ok()).toBeTruthy();
    const rows = await list.json();
    test.skip(rows.length === 0, 'family has no transactions to scope by');

    const r = await page.request.get(
      `${BASE_URL}/api/budget/items?transaction_id=${rows[0].id}`,
    );
    expect(r.ok()).toBeTruthy();
    const items = await r.json();
    expect(Array.isArray(items)).toBeTruthy();
    // Whatever comes back must belong to the transaction we asked about.
    for (const it of items) expect(it.transaction_id).toBe(rows[0].id);
  });

  test('the transaction list reports item_count as a number', async ({ page }) => {
    await loginAsParent(page);
    const r = await page.request.get(`${BASE_URL}/api/budget/transactions/?limit=5`);
    const rows = await r.json();
    test.skip(rows.length === 0, 'family has no transactions');
    for (const row of rows) {
      expect(typeof row.item_count).toBe('number');
    }
  });

  test('opening a transaction renders its items, each linking to price history', async ({ page }) => {
    await loginAsParent(page);
    // The items endpoint is stubbed rather than driving a real scan: a stubbed
    // scan persists nothing, so asserting against it would be theatre. What is
    // under test here is the read-back rendering.
    await page.route('**/api/budget/items*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            transaction_id: 'tx-1',
            name: 'Leche Alpura 1L',
            normalized_name: 'leche alpura',
            qty: 2,
            unit_price_cents: 2900,
            total_cents: 5800,
          },
          {
            transaction_id: 'tx-1',
            name: 'Pan Bimbo',
            normalized_name: 'pan bimbo',
            qty: 1,
            unit_price_cents: 2900,
            total_cents: 2900,
          },
        ]),
      }),
    );

    await ensureTransaction(page);
    await page.goto(`${BASE_URL}/budget/transactions`);
    await expect(page.locator('.tx-row').first()).toBeVisible();
    await page.locator('.tx-row').first().click();

    const panel = page.locator('#receipt-items-panel');
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('Leche Alpura 1L');
    await expect(panel).toContainText('Pan Bimbo');
    await expect(panel).toContainText('2×');
    await expect(panel).toContainText('$58.00');
    // Footer totals the lines so a mismatch with the transaction is visible.
    await expect(panel).toContainText('$87.00');
    // Each row is a way into that product's price history.
    await expect(
      panel.locator('a[href="/budget/items/leche%20alpura"]'),
    ).toHaveCount(1);
  });

  test('a transaction with no items hides the panel instead of showing an empty box', async ({ page }) => {
    await loginAsParent(page);
    await page.route('**/api/budget/items*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    );
    await ensureTransaction(page);
    await page.goto(`${BASE_URL}/budget/transactions`);
    const row = page.locator('.tx-row').first();
    await expect(row).toBeVisible();
    await row.click();
    await page.waitForTimeout(600);
    // Assert it EXISTS first: toBeHidden() also passes for an element that was
    // never rendered, which is how an earlier version of this test passed
    // against a frontend build that had no panel at all.
    await expect(page.locator('#receipt-items-panel')).toHaveCount(1);
    await expect(page.locator('#receipt-items-panel')).toBeHidden();
  });

  test('the route the item page used to link to really is a 404', async ({ page }) => {
    // Documents why the link changed: /budget/transactions/<id> is not a route
    // (only the list page and /new exist), so every row on the item history
    // page dead-ended. ?tx=<id> opens the edit sheet and is a real page.
    await loginAsParent(page);
    const dead = await page.request.get(
      `${BASE_URL}/budget/transactions/00000000-0000-0000-0000-000000000000`,
    );
    expect(dead.status()).toBe(404);

    const live = await page.request.get(
      `${BASE_URL}/budget/transactions?tx=00000000-0000-0000-0000-000000000000`,
    );
    expect(live.status()).toBe(200);
  });

  test('the item history page links back to a route that exists', async ({ page }) => {
    await loginAsParent(page);
    const r = await page.request.get(`${BASE_URL}/api/budget/items?limit=1`);
    const items = await r.json();
    test.skip(!Array.isArray(items) || items.length === 0, 'family has no receipt items');

    await page.goto(
      `${BASE_URL}/budget/items/${encodeURIComponent(items[0].normalized_name)}`,
    );
    const href = await page.locator('ul a').first().getAttribute('href');
    expect(href).toContain('/budget/transactions?tx=');
  });


  test('the price-comparison panel stays hidden when the integration is off', async ({ page }) => {
    // Both "this family never opted into the price-checker" and "the agent has
    // not answered yet" were plain 404s, and the UI rendered the same
    // "Pendiente — revisa en 5 minutos" for both. Every family without the
    // integration — the default — got a permanent promise of data that was
    // never coming, on every transaction.
    await loginAsParent(page);
    await ensureTransaction(page);

    const r = await page.request.get(
      `${BASE_URL}/api/budget/price-comparison/00000000-0000-0000-0000-000000000000`,
    );
    expect(r.status()).toBe(404);
    const body = await r.json();
    expect(body.detail.code).toBe('a2a_not_configured');

    await page.goto(`${BASE_URL}/budget/transactions`);
    await expect(page.locator('.tx-row').first()).toBeVisible();
    await page.locator('.tx-row').first().click();
    await page.waitForTimeout(800);

    // Present in the DOM (so this cannot pass on a missing element) but never
    // revealed.
    await expect(page.locator('#price-comparison-panel')).toHaveCount(1);
    await expect(page.locator('#price-comparison-panel')).toBeHidden();
  });

});
