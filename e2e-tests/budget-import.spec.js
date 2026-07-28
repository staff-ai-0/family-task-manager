const { test, expect } = require('@playwright/test');
const { BASE_URL, loginAsParent } = require('./helpers/auth');

/**
 * /budget/import — CSV statement import (parent only).
 *
 * The page posts multipart to /api/budget/transactions/import/csv through the
 * same-origin Astro proxy. Column detection is automatic for the generic
 * header set (date / amount / description — see CSVImportService.FORMATS), so
 * these fixtures deliberately use the plainest possible header row and leave
 * the manual column-mapping selects on "(auto)".
 *
 * Every fixture is stamped with Date.now(): prevent_duplicates keys on
 * (account, date, amount, imported_id=description), so a re-run with a fixed
 * payee would be counted as skipped duplicates instead of imports.
 */

/** Resolve a target account, creating one only if the family has none. */
async function ensureAccount(page) {
  const res = await page.request.get(`${BASE_URL}/api/budget/accounts/`);
  expect(res.ok()).toBeTruthy();
  const accounts = await res.json();
  if (accounts.length > 0) return accounts[0];

  // budget_account is a metered feature — a capped free-tier family gets 403.
  const created = await page.request.post(`${BASE_URL}/api/budget/accounts/`, {
    data: { name: `E2E Import Target ${Date.now()}`, type: 'checking' },
  });
  test.skip(
    created.status() === 403,
    'family has no budget account and is at its budget_account plan limit'
  );
  expect(created.status()).toBe(201);
  return created.json();
}

function csvFixture(stamp) {
  const rows = [
    { date: '2026-01-15', amount: '-12.34', cents: -1234, payee: `E2E Import A ${stamp}` },
    { date: '2026-01-16', amount: '56.78', cents: 5678, payee: `E2E Import B ${stamp}` },
  ];
  const text =
    ['date,amount,description', ...rows.map((r) => `${r.date},${r.amount},${r.payee}`)].join('\n') +
    '\n';
  return {
    rows,
    file: { name: `e2e-import-${stamp}.csv`, mimeType: 'text/csv', buffer: Buffer.from(text) },
  };
}

/** Fill the import form and submit; returns the import API response. */
async function submitImport(page, accountId, file) {
  await page.selectOption('#account-id', accountId);
  await page.locator('#csv-file').setInputFiles(file);
  await expect(page.locator('#file-info')).toContainText(file.name);

  const posted = page.waitForResponse(
    (r) => r.url().includes('/api/budget/transactions/import/csv') && r.request().method() === 'POST'
  );
  await page.locator('#import-btn').click();
  return posted;
}

test.describe('Budget CSV import', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsParent(page);
    await page.goto(`${BASE_URL}/budget/import`);
    await page.waitForLoadState('networkidle');
    test.skip(page.url().includes('module_off=1'), 'the budget module is off for this family');
    await expect(page.locator('#import-form')).toBeVisible();
  });

  test('imports a CSV and the transactions land on the account', { tag: '@smoke' }, async ({ page }) => {
    const account = await ensureAccount(page);
    const { rows, file } = csvFixture(Date.now());

    expect((await submitImport(page, account.id, file)).ok()).toBeTruthy();

    // On success the form is swapped for the results panel.
    await expect(page.locator('#results')).toBeVisible();
    await expect(page.locator('#import-form')).toBeHidden();
    // Results tiles render in a fixed order: total rows, then successful imports
    // (budget/import.astro → displayResults).
    const counts = page.locator('#results-content p.text-lg');
    await expect(counts.nth(0)).toHaveText(String(rows.length));
    await expect(counts.nth(1)).toHaveText(String(rows.length));

    // The real assertion: the rows exist on the account, with the right signed
    // amounts, and carry the CSV description as imported_id.
    const listed = await (
      await page.request.get(
        `${BASE_URL}/api/budget/transactions/?account_id=${account.id}` +
          `&start_date=${rows[0].date}&end_date=${rows[rows.length - 1].date}&limit=500`
      )
    ).json();
    for (const row of rows) {
      const tx = listed.find((t) => t.imported_id === row.payee);
      expect(tx, `imported transaction for "${row.payee}"`).toBeTruthy();
      expect(tx.amount).toBe(row.cents);
      expect(tx.date).toBe(row.date);
    }
  });

  test('re-importing the same file is skipped, not duplicated', async ({ page }) => {
    const account = await ensureAccount(page);
    const { rows, file } = csvFixture(Date.now());

    expect((await submitImport(page, account.id, file)).ok()).toBeTruthy();
    await expect(page.locator('#results')).toBeVisible();

    // Second pass over the identical file with "Evitar duplicados" left on.
    await page.goto(`${BASE_URL}/budget/import`);
    await page.waitForLoadState('networkidle');
    expect((await submitImport(page, account.id, file)).ok()).toBeTruthy();
    await expect(page.locator('#results')).toBeVisible();

    const counts = page.locator('#results-content p.text-lg');
    await expect(counts.nth(0)).toHaveText(String(rows.length)); // parsed again
    await expect(counts.nth(1)).toHaveText('0'); // none imported
    await expect(counts.nth(2)).toHaveText(String(rows.length)); // all skipped

    // And the ledger still holds exactly one copy of each row.
    const listed = await (
      await page.request.get(
        `${BASE_URL}/api/budget/transactions/?account_id=${account.id}` +
          `&start_date=${rows[0].date}&end_date=${rows[rows.length - 1].date}&limit=500`
      )
    ).json();
    for (const row of rows) {
      expect(listed.filter((t) => t.imported_id === row.payee)).toHaveLength(1);
    }
  });

  test('refuses to submit without an account and a file', async ({ page }) => {
    // Guards the client-side precondition: no account + no file must not fire
    // a request at all (the endpoint would 422 on a missing account_id).
    let posted = false;
    page.on('request', (r) => {
      if (r.url().includes('/transactions/import/')) posted = true;
    });
    await page.locator('#import-btn').click();
    await page.waitForTimeout(500);
    await expect(page.locator('#results')).toBeHidden();
    expect(posted).toBe(false);
  });
});
