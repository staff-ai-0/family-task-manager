const { test, expect } = require('@playwright/test');

test.describe('Authentication', () => {
  const BASE_URL = 'http://localhost:3003';
  const DEMO_USER = {
    email: 'mom@demo.com',
    password: 'password123',
  };
  const NEW_USER = {
    email: `test-${Date.now()}@demo.com`,
    password: 'TestPassword123!',
    familyName: `Family-${Date.now()}`,
  };

  test.describe('Login Flow', () => {
    test('should login with valid credentials and redirect to dashboard', async ({ page }) => {
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState('networkidle');

      // Fill in login form
      await page.fill('input[name="email"]', DEMO_USER.email);
      await page.fill('input[name="password"]', DEMO_USER.password);

      // Submit form
      await page.click('button[type="submit"]');

      // Wait for navigation to dashboard
      await page.waitForURL('**/dashboard', { timeout: 10000 });

      // Verify we're on dashboard
      expect(page.url()).toContain('/dashboard');

      // Verify access token is set
      const cookies = await page.context().cookies();
      const accessToken = cookies.find(c => c.name === 'access_token');
      expect(accessToken).toBeDefined();
      expect(accessToken.value).toBeTruthy();
    });

    test('should show error message with invalid credentials', async ({ page }) => {
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState('networkidle');

      // Fill in invalid credentials
      await page.fill('input[name="email"]', 'invalid@test.com');
      await page.fill('input[name="password"]', 'wrongpassword');

      // Submit form
      await page.click('button[type="submit"]');

      // Wait for error message
      const errorMessage = page.locator('.bg-red-50');
      await errorMessage.waitFor({ timeout: 5000 });

      // Verify error message is visible
      const errorText = await errorMessage.textContent();
      expect(errorText).toBeTruthy();
    });

    test('should require email field', async ({ page }) => {
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState('networkidle');

      // Try to submit without email
      await page.fill('input[name="password"]', DEMO_USER.password);
      const emailInput = page.locator('input[name="email"]');

      // Check if HTML5 validation prevents submission
      const isRequired = await emailInput.evaluate(el => el.required);
      expect(isRequired).toBe(true);
    });

    test('should require password field', async ({ page }) => {
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState('networkidle');

      // Try to submit without password
      await page.fill('input[name="email"]', DEMO_USER.email);
      const passwordInput = page.locator('input[name="password"]');

      // Check if HTML5 validation prevents submission
      const isRequired = await passwordInput.evaluate(el => el.required);
      expect(isRequired).toBe(true);
    });
  });

  test.describe('Registration Flow', () => {
    test('should register a new family with valid data', async ({ page }) => {
      await page.goto(`${BASE_URL}/register`);
      await page.waitForLoadState('networkidle');

      // Fill in registration form
      await page.fill('input[name="email"]', NEW_USER.email);
      await page.fill('input[name="password"]', NEW_USER.password);
      await page.fill('input[name="confirm_password"]', NEW_USER.password);
      await page.fill('input[name="name"]', 'John Doe');
      await page.fill('input[name="family_name"]', NEW_USER.familyName);

      // Submit form
      await page.click('button[type="submit"]');

      // Wait for success message or redirect
      await page.waitForURL('**/dashboard', { timeout: 10000 }).catch(() => {
        // If redirect doesn't happen, check for success message
      });

      // Verify we're logged in (either on dashboard or have access token)
      const cookies = await page.context().cookies();
      const accessToken = cookies.find(c => c.name === 'access_token');
      expect(accessToken).toBeDefined();
    });

    test('should show error when passwords do not match', async ({ page }) => {
      await page.goto(`${BASE_URL}/register`);
      await page.waitForLoadState('networkidle');

      // Fill in registration form with mismatched passwords
      await page.fill('input[name="email"]', NEW_USER.email);
      await page.fill('input[name="password"]', NEW_USER.password);
      await page.fill('input[name="confirm_password"]', 'DifferentPassword123!');
      await page.fill('input[name="name"]', 'John Doe');
      await page.fill('input[name="family_name"]', NEW_USER.familyName);

      // Try to submit
      const submitButton = page.locator('button[type="submit"]');
      const isDisabled = await submitButton.evaluate(el => el.disabled);
      
      // Should either be disabled or show error on submit
      if (!isDisabled) {
        await page.click('button[type="submit"]');
        const errorMessage = page.locator('.bg-red-50');
        await errorMessage.waitFor({ timeout: 5000 });
        const errorText = await errorMessage.textContent();
        expect(errorText).toBeTruthy();
      }
    });
  });

  test.describe('Logout Flow', () => {
    test('should logout and clear access token', async ({ page }) => {
      // Login first
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState('networkidle');
      await page.fill('input[name="email"]', DEMO_USER.email);
      await page.fill('input[name="password"]', DEMO_USER.password);
      await page.click('button[type="submit"]');
      await page.waitForURL('**/dashboard', { timeout: 10000 });

      // Verify access token is set
      let cookies = await page.context().cookies();
      let accessToken = cookies.find(c => c.name === 'access_token');
      expect(accessToken).toBeDefined();

      // Find and click logout button (typically in profile menu)
      // Try to click profile/menu button
      const profileButton = page.locator('button[aria-label*="profile"], a[href="/profile"]').first();
      if (await profileButton.count() > 0) {
        await profileButton.click();
      }

      // Look for logout link/button
      const logoutButton = page.locator('button:has-text("Logout"), a:has-text("Logout"), button:has-text("Sign out"), a:has-text("Sign out")').first();
      if (await logoutButton.count() > 0) {
        await logoutButton.click();
        
        // Wait for redirect to login
        await page.waitForURL('**/login', { timeout: 5000 });

        // Verify access token is cleared
        cookies = await page.context().cookies();
        accessToken = cookies.find(c => c.name === 'access_token');
        expect(accessToken).toBeUndefined();
      }
    });
  });

  test.describe('Session Management', () => {
    test('should redirect to login if accessing dashboard without token', async ({ page }) => {
      // Try to access dashboard directly without login
      await page.goto(`${BASE_URL}/dashboard`);
      await page.waitForLoadState('networkidle');

      // Should redirect to login
      expect(page.url()).toContain('/login');
    });

    test('should restore session from valid access token', async ({ page, context }) => {
      // Login first
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState('networkidle');
      await page.fill('input[name="email"]', DEMO_USER.email);
      await page.fill('input[name="password"]', DEMO_USER.password);
      await page.click('button[type="submit"]');
      await page.waitForURL('**/dashboard', { timeout: 10000 });

      // Get the current URL (should be dashboard)
      const initialUrl = page.url();
      expect(initialUrl).toContain('/dashboard');

      // Navigate away and back
      await page.goto(`${BASE_URL}/rewards`);
      await page.waitForLoadState('networkidle');

      // Verify we can access protected pages without re-login
      expect(page.url()).toContain('/rewards');

      // Go back to dashboard
      await page.goto(`${BASE_URL}/dashboard`);
      await page.waitForLoadState('networkidle');
      expect(page.url()).toContain('/dashboard');
    });
  });
});
