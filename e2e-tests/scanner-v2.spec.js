const { test, expect } = require('@playwright/test');
const { loginAsParent } = require('./helpers/auth');

test.describe('Scanner v2', () => {
  test('one-tap snap → confirm card', async ({ page }) => {
    await loginAsParent(page);
    await page.goto('/budget/scan-receipt');
    await expect(page.locator('text=Snap receipt')).toBeVisible();
    // The native camera input cannot be driven; assert UI scaffolding.
    await expect(page.locator('#confirm-card.hidden')).toHaveCount(1);
  });

  test('duplicate modal flow', async ({ page }) => {
    // requires a backend stub or pre-seeded recent tx; left as a fixture spec
    test.skip(true, 'needs backend stub for dup-flow; covered by API test 26');
  });

  test('FX display when accounts differ', async ({ page }) => {
    test.skip(true, 'needs backend stub; covered by API test 14');
  });

  test('IVA pill renders when present', async ({ page }) => {
    test.skip(true, 'needs backend stub; covered by API test 16');
  });

  test('trend badges only when sample_size >= 3', async ({ page }) => {
    test.skip(true, 'needs seeded item history');
  });
});
