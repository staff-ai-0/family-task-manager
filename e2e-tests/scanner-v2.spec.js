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

  // TODO: add real E2E coverage for: duplicate modal flow, FX cross-currency display,
  // IVA pill rendering, item-trend badges. Each needs a mock-able backend stub for the
  // /api/budget/transactions/scan-receipt POST. Tracked in: TBD-followup.
});
