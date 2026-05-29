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

  // The following four flows need a mock-able backend stub for the
  // /api/budget/transactions/scan-receipt POST. Each is shipped as test.skip
  // (with a comment pointing at the backend coverage that DOES exist) so
  // CI shows "skipped: 4" and the coverage gap stays visible — better than
  // silently passing with one happy-path test.
  test.skip("duplicate modal flow — needs API mock layer (see test_endpoint_returns_409_on_dup)", () => {});
  test.skip("FX display when accounts differ — covered by test_pipeline_stores_fx_when_currencies_differ", () => {});
  test.skip("IVA pill renders when present — covered by test_pipeline_creates_tx_with_items_and_fx", () => {});
  test.skip("trend badges only when sample_size >= 3 — covered by test_get_trend_returns_null_below_sample", () => {});
});
