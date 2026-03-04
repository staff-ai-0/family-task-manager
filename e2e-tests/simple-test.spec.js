const { test, expect } = require('@playwright/test');

test('simple frontend check', async ({ page }) => {
  await page.goto('http://localhost:3003/');
  await page.waitForLoadState('networkidle');
  expect(page.url()).toContain('localhost:3003');
});
