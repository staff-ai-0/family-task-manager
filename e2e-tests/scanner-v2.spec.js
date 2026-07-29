const { test, expect } = require('@playwright/test');
const { loginAsParent } = require('./helpers/auth');

// 1x1 PNG — the file only has to exist; every scan response is stubbed below.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

const receiptFile = (name = 'ticket.png') => ({
  name,
  mimeType: 'image/png',
  buffer: PNG,
});

/** Stub the scan endpoint with a fixed status + body. */
async function stubScan(page, status, body) {
  await page.route('**/api/budget/transactions/scan-receipt*', (route) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    }),
  );
}

const successBody = {
  success: true,
  transaction_id: 'tx-1',
  transaction: {
    payee_name: 'Soriana',
    amount: -34550,
    currency: 'MXN',
    account_name: 'Tarjeta BBVA',
    iva_cents: 4766,
  },
  account_match: { strategy: 'card_last4' },
  items: [
    { name: 'Leche 1L', qty: 2, total_cents: 5800, normalized_name: 'leche-1l' },
    { name: 'Pan', qty: 1, total_cents: 2900, normalized_name: 'pan' },
  ],
  trends: [{ normalized_name: 'leche-1l', sample_size: 5, pct_change: 0.18 }],
};

test.describe('Scanner v2 — in-place sheet', () => {
  test('the sheet is mounted on budget pages, not only on /budget/scan-receipt', async ({ page }) => {
    // The whole point of the refactor: a scan starts from wherever the user
    // already is, with no navigation to a page whose only job was to show a
    // second "take a photo" button.
    await loginAsParent(page);
    await page.goto('/budget/transactions');
    await expect(page.locator('#receipt-scan-sheet')).toHaveCount(1);
    await expect(page.locator('#rss-input')).toHaveCount(1);
  });

  test('the file input accepts batches and does not pin iOS to the camera', async ({ page }) => {
    // `capture` is what forced the old page to carry three buttons: it pins
    // iOS to the lens, so "upload" and "bulk" needed inputs of their own.
    await loginAsParent(page);
    await page.goto('/budget/transactions');
    const input = page.locator('#rss-input');
    await expect(input).toHaveAttribute('multiple', '');
    expect(await input.getAttribute('capture')).toBeNull();
  });

  test('tapping scan does not navigate away', async ({ page }) => {
    await loginAsParent(page);
    await page.goto('/budget/transactions');
    const before = page.url();
    await page.locator('[data-scan-receipt-open]').first().click();
    await page.waitForTimeout(300);
    expect(page.url()).toBe(before);
  });

  test('a scanned receipt renders the confirm sheet in place', async ({ page }) => {
    await loginAsParent(page);
    await stubScan(page, 200, successBody);
    await page.goto('/budget/transactions');

    await page.locator('#rss-input').setInputFiles(receiptFile());

    const result = page.locator('#rss-result');
    await expect(result).toBeVisible();
    await expect(result).toContainText('Soriana');
    await expect(result).toContainText('345.50');
    await expect(result).toContainText('Tarjeta BBVA');
    await expect(result).toContainText('IVA');
    // Trend badge only for the item with sample_size >= 3 and a >= 5% move.
    await expect(result).toContainText('18%');
    // Still on the transactions page behind the sheet.
    expect(page.url()).toContain('/budget/transactions');
  });

  test('a duplicate opens the "already scanned" dialog', async ({ page }) => {
    await loginAsParent(page);
    await stubScan(page, 409, {
      dup_warning: {
        payee: 'Soriana',
        amount_cents: 34550,
        scanned_at: new Date().toISOString(),
        existing_transaction_id: 'tx-0',
      },
      transaction: { currency: 'MXN' },
    });
    await page.goto('/budget/transactions');

    await page.locator('#rss-input').setInputFiles(receiptFile());

    const dup = page.locator('#rss-dup');
    await expect(dup).toBeVisible();
    await expect(dup).toContainText(/Ya escaneado|Already scanned/i);
    await expect(dup).toContainText('Soriana');
  });

  test('a low-confidence scan is routed to the review queue', async ({ page }) => {
    await loginAsParent(page);
    await stubScan(page, 200, { draft_id: 'draft-1' });
    await page.goto('/budget/transactions');

    await page.locator('#rss-input').setInputFiles(receiptFile());
    await page.waitForURL('**/budget/receipt-drafts');
  });

  test('several files at once run as a batch', async ({ page }) => {
    await loginAsParent(page);
    await stubScan(page, 200, successBody);
    await page.goto('/budget/transactions');

    await page
      .locator('#rss-input')
      .setInputFiles([receiptFile('a.png'), receiptFile('b.png'), receiptFile('c.png')]);

    const result = page.locator('#rss-result');
    await expect(result).toBeVisible();
    await expect(result).toContainText('a.png');
    await expect(result).toContainText('3 / 3');
    await expect(result).toContainText(/3 creados|3 created/);
  });

  test('the landing page still works as an addressable entry point', async ({ page }) => {
    // Email links, the drawer's fallback href, and the FAB's no-JS fallback
    // all point here.
    await loginAsParent(page);
    await page.goto('/budget/scan-receipt');
    await expect(page.getByText(/Take or choose a photo|Elegir o tomar foto/i)).toBeVisible();
    await expect(page.locator('#rss-input')).toHaveCount(1);
  });
});
