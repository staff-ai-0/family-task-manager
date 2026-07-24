// @ts-check
import { test } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const EMAIL = process.env.E2E_EMAIL || 'e2e-fresh@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'fresh1234';

test('screenshot login page', async ({ page }) => {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: 'screenshot-login.png', fullPage: true });
  console.log('Login page screenshot saved to screenshot-login.png');
});

test('screenshot dashboard page', async ({ page }) => {
  // Login first
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('#login-submit-btn');
  await page.waitForURL(/\/(dashboard|parent)$/, { timeout: 30000 });
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: 'screenshot-dashboard.png', fullPage: true });
  console.log('Dashboard screenshot saved to screenshot-dashboard.png');
});
