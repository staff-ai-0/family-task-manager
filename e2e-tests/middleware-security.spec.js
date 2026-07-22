const { test, expect } = require('@playwright/test');

/**
 * Regression tests for the launch-P0 middleware fixes (PR #92):
 * 1. Anonymous visitors reach the custom 404 for unmatched paths instead of
 *    being 302'd to /login (middleware routePattern === "/404" fall-through).
 * 2. Protected pages still 302 anonymous visitors to /login.
 * 3. Security headers (X-Content-Type-Options / Referrer-Policy) are applied
 *    to middleware-generated responses too: the /login redirect, CSRF 403s,
 *    and API 401s — not just pass-through page responses.
 * 4. The auto-set lang cookie only appears on HTML page responses, never on
 *    API routes (no Set-Cookie: lang on every JSON response).
 *
 * All tests are anonymous — no login/seeded DB required.
 */
test.describe('Middleware security & 404 reachability', () => {
  const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';

  test('anonymous unmatched path renders the custom 404 (no /login bounce)', async ({ request }) => {
    const res = await request.get(`${BASE_URL}/definitely-not-a-real-page`, {
      maxRedirects: 0,
    });
    expect(res.status()).toBe(404);
    const body = await res.text();
    expect(body).toContain('404');
    // Security headers present on the 404 page
    expect(res.headers()['x-content-type-options']).toBe('nosniff');
    expect(res.headers()['x-frame-options']).toBe('DENY');
  });

  test('anonymous /dashboard still redirects to /login with security headers', async ({ request }) => {
    const res = await request.get(`${BASE_URL}/dashboard`, { maxRedirects: 0 });
    expect(res.status()).toBe(302);
    // Carries ?next= so login can resume at the original destination
    // (frontend/src/middleware.ts) — /login itself validates+consumes it.
    expect(res.headers()['location']).toBe('/login?next=%2Fdashboard');
    // withSecurityHeaders must wrap middleware-generated redirects too
    expect(res.headers()['x-content-type-options']).toBe('nosniff');
    expect(res.headers()['referrer-policy']).toBe('strict-origin-when-cross-origin');
  });

  test('CSRF violation returns 403 JSON with security headers', async ({ request }) => {
    const res = await request.post(`${BASE_URL}/api/invitations/send`, {
      headers: {
        Origin: 'http://evil.example',
        'Content-Type': 'application/json',
      },
      data: {},
      maxRedirects: 0,
    });
    expect(res.status()).toBe(403);
    const body = await res.json();
    expect(body.detail).toBe('CSRF validation failed');
    expect(res.headers()['x-content-type-options']).toBe('nosniff');
    expect(res.headers()['referrer-policy']).toBe('strict-origin-when-cross-origin');
  });

  test('anonymous API request gets 401 with security headers and NO lang cookie', async ({ request }) => {
    const res = await request.get(`${BASE_URL}/api/tasks`, { maxRedirects: 0 });
    expect(res.status()).toBe(401);
    expect(res.headers()['x-content-type-options']).toBe('nosniff');
    // lang cookie must never be auto-set on API responses
    const setCookies = res.headersArray()
      .filter((h) => h.name.toLowerCase() === 'set-cookie')
      .map((h) => h.value);
    expect(setCookies.some((c) => c.startsWith('lang='))).toBe(false);
  });

  test('HTML page response auto-sets the lang cookie when absent', async ({ request }) => {
    const res = await request.get(`${BASE_URL}/login`, { maxRedirects: 0 });
    expect(res.status()).toBe(200);
    const setCookies = res.headersArray()
      .filter((h) => h.name.toLowerCase() === 'set-cookie')
      .map((h) => h.value);
    const langCookie = setCookies.find((c) => c.startsWith('lang='));
    expect(langCookie).toBeTruthy();
    expect(langCookie).toContain('SameSite=Lax');
  });
});
