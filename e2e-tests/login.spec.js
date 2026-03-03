const { test, expect } = require('@playwright/test');

test.describe('Login Flow', () => {
  const BASE_URL = 'https://family.agent-ia.mx';

  test('should login with email and password and redirect to dashboard', async ({ page }) => {
    // Enable console logging
    page.on('console', msg => console.log('Browser console:', msg.text()));
    
    // Listen for requests
    page.on('request', request => {
      if (request.url().includes('/api/')) {
        console.log('Request:', request.method(), request.url());
      }
    });
    
    // Listen for responses
    page.on('response', response => {
      if (response.url().includes('/api/')) {
        console.log('Response:', response.status(), response.url());
      }
    });

    // Go to login page
    console.log('1. Navigating to login page...');
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');
    
    // Take screenshot of login page
    await page.screenshot({ path: 'login-page.png' });
    console.log('2. Login page loaded, screenshot saved');

    // Check if Google Sign-In button exists
    const googleButton = page.locator('.g_id_signin');
    const hasGoogleButton = await googleButton.count() > 0;
    console.log('3. Google Sign-In button present:', hasGoogleButton);

    // Fill in email and password
    console.log('4. Filling in credentials...');
    await page.fill('input[name="email"]', 'mom@demo.com');
    await page.fill('input[name="password"]', 'password123');
    
    // Take screenshot before submit
    await page.screenshot({ path: 'before-submit.png' });
    console.log('5. Credentials filled, screenshot saved');

    // Submit form
    console.log('6. Submitting form...');
    await page.click('button[type="submit"]');
    
    // Wait for navigation or error
    console.log('7. Waiting for navigation...');
    const responsePromise = page.waitForResponse(resp => resp.url().includes('/api/auth/login'), { timeout: 5000 }).catch(() => null);
    const response = await responsePromise;
    
    if (response) {
      console.log('7a. Response status:', response.status());
      console.log('7b. Response headers:', await response.allHeaders());
    }
    
    // Wait for URL change or timeout
    await page.waitForURL('**/dashboard', { timeout: 5000 }).catch(() => console.log('No redirect to dashboard'));
    
    // Take screenshot after submit
    await page.screenshot({ path: 'after-submit.png' });
    
    // Check current URL
    const currentUrl = page.url();
    console.log('8. Current URL after submit:', currentUrl);
    
    // Check for error messages
    const errorDiv = page.locator('.bg-red-50');
    const errorCount = await errorDiv.count();
    if (errorCount > 0) {
      const errorMessage = await errorDiv.textContent();
      console.log('9. Error message found:', errorMessage);
    } else {
      console.log('9. No error message found');
    }
    
    // Check for any visible text on page
    const bodyText = await page.locator('body').textContent();
    console.log('9a. Page contains "dashboard":', bodyText.toLowerCase().includes('dashboard'));
    console.log('9b. Page contains "welcome back":', bodyText.toLowerCase().includes('welcome back'));
    
    // Check cookies BEFORE context closes
    let accessToken = null;
    try {
      const cookies = await page.context().cookies();
      accessToken = cookies.find(c => c.name === 'access_token');
      console.log('10. Access token cookie:', accessToken ? 'SET' : 'NOT SET');
      if (accessToken) {
        console.log('    Token value:', accessToken.value.substring(0, 50) + '...');
        console.log('    Secure:', accessToken.secure, 'HttpOnly:', accessToken.httpOnly);
      }
    } catch (e) {
      console.log('10. Could not check cookies:', e.message);
    }
    
    // Check if redirected to dashboard
    const isDashboard = currentUrl.includes('/dashboard');
    console.log('11. Redirected to dashboard:', isDashboard);
    
    if (!isDashboard) {
      console.log('ERROR: Login failed, still on:', currentUrl);
      // Get page content for debugging
      const content = await page.content();
      console.log('Page HTML length:', content.length);
    }
    
    // Assertions
    expect(accessToken, 'Access token should be set').toBeDefined();
    expect(currentUrl, 'Should redirect to dashboard').toContain('/dashboard');
  });
});
