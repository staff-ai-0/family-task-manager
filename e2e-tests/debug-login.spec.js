const { test, expect } = require('@playwright/test');

test('debug login response headers', async ({ page }) => {
  const BASE_URL = 'https://family.agent-ia.mx';
  
  // Capture response headers
  page.on('response', async response => {
    if (response.url().includes('/api/auth/login')) {
      console.log('\n=== LOGIN RESPONSE ===');
      console.log('Status:', response.status());
      console.log('Status Text:', response.statusText());
      console.log('URL:', response.url());
      
      const headers = await response.allHeaders();
      console.log('\nAll Headers:');
      for (const [key, value] of Object.entries(headers)) {
        console.log(`  ${key}: ${value}`);
      }
      
      console.log('\n======================\n');
    }
  });
  
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="email"]', 'mom@demo.com');
  await page.fill('input[name="password"]', 'password123');
  
  // Click and wait
  await page.click('button[type="submit"]');
  
  // Wait a bit
  await page.waitForTimeout(2000);
  
  console.log('\nFinal URL:', page.url());
  
  // Check cookies
  const cookies = await page.context().cookies();
  const accessToken = cookies.find(c => c.name === 'access_token');
  console.log('\nCookie check:');
  console.log('Access token:', accessToken ? 'PRESENT' : 'MISSING');
  if (accessToken) {
    console.log('Domain:', accessToken.domain);
    console.log('Path:', accessToken.path);
    console.log('Secure:', accessToken.secure);
    console.log('HttpOnly:', accessToken.httpOnly);
    console.log('SameSite:', accessToken.sameSite);
  }
});
