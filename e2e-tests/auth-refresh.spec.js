const { test, expect } = require('@playwright/test');
const { loginAsParent, BASE_URL } = require('./helpers/auth');

test.describe('JWT access + refresh', () => {
  test('expired access token is transparently refreshed (no login bounce)', async ({ page, context }) => {
    await loginAsParent(page);
    await expect(page).toHaveURL(/\/(dashboard|parent)/);

    // Simulate an expired/absent access token while keeping the refresh cookie:
    // drop only access_token, leave refresh_token in place.
    const cookies = await context.cookies();
    expect(cookies.find((c) => c.name === 'refresh_token')).toBeTruthy();
    const kept = cookies.filter((c) => c.name !== 'access_token');
    await context.clearCookies();
    await context.addCookies(kept);

    // Navigating to a protected page must refresh in middleware, not redirect.
    await page.goto(`${BASE_URL}/dashboard`);
    await expect(page).toHaveURL(/\/(dashboard|parent)/);

    const after = await context.cookies();
    expect(after.find((c) => c.name === 'access_token')).toBeTruthy();
  });

  test('logout invalidates the refresh token (logout-everywhere)', async ({ page, context }) => {
    await loginAsParent(page);
    const before = await context.cookies();
    const refresh = before.find((c) => c.name === 'refresh_token');
    expect(refresh).toBeTruthy();

    // Log out (bumps server token_version), then replant the old refresh token.
    await page.request.post(`${BASE_URL}/api/auth/logout`);
    await context.clearCookies();
    await context.addCookies([{ name: 'refresh_token', value: refresh.value, url: BASE_URL }]);

    // The BFF refresh route must now fail — the old refresh token is revoked.
    const resp = await page.request.post(`${BASE_URL}/api/auth/refresh`);
    expect(resp.status()).toBe(401);
  });

  test('no cookies redirects to login', async ({ page, context }) => {
    await context.clearCookies();
    await page.goto(`${BASE_URL}/dashboard`);
    await expect(page).toHaveURL(/\/login/);
  });
});
