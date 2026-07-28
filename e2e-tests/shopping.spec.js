const { test, expect } = require('@playwright/test');
const { loginAsParent } = require('./helpers/auth');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const EMAIL = process.env.E2E_EMAIL || 'e2e-fresh@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'fresh1234';


test.describe('Shopping list', () => {
  test('parent can create a list, add an item, check it off', async ({ page }) => {
    await loginAsParent(page);
    await page.goto(`${BASE_URL}/shopping`);

    // Create list
    const listName = `Test list ${Date.now()}`;
    await page.fill('input[name="name"][maxlength="120"]', listName);
    await page.getByRole('button', { name: /add|agregar/i }).first().click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: listName })).toBeVisible();

    // Select the list (chip link contains list name)
    await page.locator(`a:has-text("${listName}")`).first().click();
    await page.waitForLoadState('networkidle');

    // Add item
    const itemName = `Tortillas ${Date.now()}`;
    await page.fill('input[name="item_name"]', itemName);
    await page.fill('input[name="qty"]', '2 pkg');
    await page.locator('button[type="submit"]:has-text("+")').click();
    await page.waitForLoadState('networkidle');
    await expect(page.getByText(itemName)).toBeVisible();

    // Check off
    const checkButton = page
      .locator('li', { hasText: itemName })
      .locator('button[aria-label="Check"]');
    if (await checkButton.count()) {
      await checkButton.first().click();
      await page.waitForLoadState('networkidle');
    }
  });

  test('check-off and delete are optimistic — no page reload', async ({ page }) => {
    await loginAsParent(page);
    await page.goto(`${BASE_URL}/shopping`);
    await page.waitForLoadState('networkidle');

    const listName = `Optimistic ${Date.now()}`;
    await page.fill('input[name="name"][maxlength="120"]', listName);
    await page.getByRole('button', { name: /add|agregar/i }).first().click();
    await page.waitForLoadState('networkidle');
    await page.locator(`a:has-text("${listName}")`).first().click();
    await page.waitForLoadState('networkidle');

    const itemName = `Leche ${Date.now()}`;
    await page.fill('input[name="item_name"]', itemName);
    await page.locator('button[type="submit"]:has-text("+")').click();
    await page.waitForLoadState('networkidle');

    const row = page.locator('li[data-item-id]', { hasText: itemName });
    await expect(row).toHaveAttribute('data-checked', 'false');
    await expect(page.locator('#pending-count')).toHaveText('1');

    // Survives only while the document is never re-created — that is the whole
    // point here (10 items checked off in the store used to be 10 reloads).
    await page.evaluate(() => { window.__stillHere = true; });

    await row.locator('button[aria-label="Check"]').click();
    await expect(row).toHaveAttribute('data-checked', 'true');
    await expect(page.locator('#pending-count')).toHaveText('0');
    expect(await page.evaluate(() => window.__stillHere)).toBe(true);

    await row.locator('button[aria-label="Delete"]').click();
    await expect(row).toHaveCount(0);
    await expect(page.locator('#items-empty')).toBeVisible();
    await expect(page.locator('#item-count')).toHaveText('0');
    expect(await page.evaluate(() => window.__stillHere)).toBe(true);
  });

  test('a failed write surfaces instead of looking like success', async ({ page }) => {
    await loginAsParent(page);
    await page.goto(`${BASE_URL}/shopping`);
    await page.waitForLoadState('networkidle');

    const listName = `Failure ${Date.now()}`;
    await page.fill('input[name="name"][maxlength="120"]', listName);
    await page.getByRole('button', { name: /add|agregar/i }).first().click();
    await page.waitForLoadState('networkidle');
    await page.locator(`a:has-text("${listName}")`).first().click();
    await page.waitForLoadState('networkidle');

    const itemName = `Pan ${Date.now()}`;
    await page.fill('input[name="item_name"]', itemName);
    await page.locator('button[type="submit"]:has-text("+")').click();
    await page.waitForLoadState('networkidle');

    await page.route('**/api/shopping/items/**', (route) =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'boom' }),
      }),
    );

    const row = page.locator('li[data-item-id]', { hasText: itemName });
    await row.locator('button[aria-label="Check"]').click();

    await expect(page.locator('#toast-container')).toContainText('boom');
    // Reverted, not left showing a checkmark the server never stored.
    await expect(row).toHaveAttribute('data-checked', 'false');
    await expect(page.locator('#pending-count')).toHaveText('1');
  });
});
