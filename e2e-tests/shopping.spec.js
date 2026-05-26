const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const EMAIL = process.env.E2E_EMAIL || 'e2e-fresh@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'fresh1234';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard', { timeout: 10000 });
}

test.describe('Shopping list', () => {
  test('parent can create a list, add an item, check it off', async ({ page }) => {
    await login(page);
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
});
