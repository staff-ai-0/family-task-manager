const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';

test('simple frontend check', async ({ page }) => {
  await page.goto(`${BASE_URL}/`);
  await page.waitForLoadState('networkidle');
  expect(page.url()).toBeTruthy();
});
