// @ts-check
import { test } from '@playwright/test';

test('screenshot login page', async ({ page }) => {
  await page.goto('https://family.agent-ia.mx/login');
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: 'screenshot-login.png', fullPage: true });
  console.log('Login page screenshot saved to screenshot-login.png');
});

test('screenshot dashboard page', async ({ page }) => {
  // Login first
  await page.goto('https://family.agent-ia.mx/login');
  await page.fill('input[name="email"]', 'mom@demo.com');
  await page.fill('input[name="password"]', 'password123');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard');
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: 'screenshot-dashboard.png', fullPage: true });
  console.log('Dashboard screenshot saved to screenshot-dashboard.png');
});
