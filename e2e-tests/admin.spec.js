const { test, expect } = require('@playwright/test');
const { BASE_URL, DEMO_USER, OPERATOR_USER, accountExists, loginAs, loginAsParent } = require('./helpers/auth');

/**
 * Operator console (/admin) — the cross-tenant support surface merged 2026-07-26.
 *
 * Two halves, deliberately separate:
 *  1. "fails closed" — runs everywhere, no operator account needed. The whole
 *     security contract of this surface is that it 404s (never 403 / never a
 *     /login bounce) for anonymous visitors and for logged-in non-operators, so
 *     the surface is not even discoverable. That is worth guarding on every run.
 *  2. "operator" — needs a real allowlisted operator (E2E_ADMIN_EMAIL /
 *     E2E_ADMIN_PASSWORD). require_superadmin
 *     (backend/app/core/dependencies.py) demands BOTH users.is_superadmin AND
 *     membership of SUPERADMIN_EMAILS, so there is no credential a test can
 *     synthesize for itself — these skip when the env vars are absent or the
 *     account is not provisioned on this deployment.
 */

test.describe('Operator console fails closed', () => {
  test('anonymous /admin is a bare 404, not a /login bounce', async ({ request }) => {
    // A 302 to /login would confirm the surface exists to a prober — see the
    // isAdminSurface zero-token short-circuit in frontend/src/middleware.ts.
    const res = await request.get(`${BASE_URL}/admin`, { maxRedirects: 0 });
    expect(res.status()).toBe(404);
  });

  test('anonymous /api/admin/* is a 404, not a 401', async ({ request }) => {
    const res = await request.get(`${BASE_URL}/api/admin/overview`, { maxRedirects: 0 });
    expect(res.status()).toBe(404);
    expect((await res.json()).detail).toBe('Not Found');
  });

  test('a logged-in non-operator parent gets 404 on the console and its API', async ({ page, request }) => {
    // Skip rather than fail where the seed parent does not exist (e.g. BASE_URL
    // pointed at prod). Without this the test dies inside loginAs with a
    // waitForURL timeout that reads like a broken login page — the two
    // anonymous checks above still cover the surface on any deployment.
    test.skip(
      !(await accountExists(request, DEMO_USER.email)),
      `${DEMO_USER.email} does not exist on this deployment — set E2E_EMAIL/E2E_PASSWORD to a parent that does`
    );
    await loginAsParent(page);

    const pageRes = await page.goto(`${BASE_URL}/admin/families`);
    expect(pageRes?.status()).toBe(404);

    // Same for the proxy the console reads through — a 403 here would leak
    // that the caller merely lacks a role.
    const apiRes = await page.request.get(`${BASE_URL}/api/admin/families`, { maxRedirects: 0 });
    expect(apiRes.status()).toBe(404);
  });
});

test.describe('Operator console', () => {
  test.beforeEach(async ({ page }) => {
    test.skip(
      !OPERATOR_USER.email || !OPERATOR_USER.password,
      'E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD not set — no allowlisted operator in this environment (see e2e-tests/README.md)'
    );
    await loginAs(page, OPERATOR_USER);
    const res = await page.goto(`${BASE_URL}/admin`);
    test.skip(
      res?.status() === 404,
      `${OPERATOR_USER.email} is not a provisioned operator here (needs users.is_superadmin AND SUPERADMIN_EMAILS — see docs/DEPLOYMENT.md)`
    );
    await page.waitForLoadState('networkidle');
  });

  test('overview renders the platform pulse tiles', async ({ page }) => {
    await expect(page.locator('main h1')).toHaveText('Overview');
    // The console wraps Layout directly and ships its own chrome — no BottomNav.
    await expect(page.getByRole('link', { name: 'Operator console' })).toBeVisible();

    const main = page.locator('main');
    // A backend failure renders a red "Could not load platform state" banner
    // INSTEAD of the tiles, so asserting on tile copy asserts a live read too.
    await expect(main.getByText('not soft-deleted (includes suspended)')).toBeVisible();
    await expect(main.getByText('email confirmed')).toBeVisible();
    await expect(main.getByText('Current-state MRR')).toBeVisible();
  });

  test('family directory finds the e2e family by member email and opens it', async ({ page }) => {
    await page.goto(`${BASE_URL}/admin/families`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('main h1')).toHaveText('Families');
    await expect(page.locator('table thead th').first()).toHaveText('Family');

    // The search box matches name, join code, family id, or MEMBER EMAIL — the
    // last one is how this pins itself to the e2e tenant instead of whichever
    // tenant happens to sort first in a shared directory.
    await page.fill('input[name="q"]', DEMO_USER.email);
    await page.getByRole('button', { name: 'Search' }).click();
    await page.waitForLoadState('networkidle');

    const rows = page.locator('table tbody tr');
    expect(await rows.count()).toBeGreaterThan(0);

    const link = rows.first().locator('a[href^="/admin/families/"]');
    const familyHref = await link.getAttribute('href');
    expect(familyHref).toMatch(/^\/admin\/families\/[0-9a-f-]{36}$/);

    await link.click();
    await page.waitForLoadState('networkidle');
    expect(page.url()).toContain(familyHref);
    // Detail page renders the per-family support views.
    await expect(page.getByRole('heading', { name: 'Members' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Billing' })).toBeVisible();
  });

  test('a bounded write action lands in the audit log with its reason', async ({ page }) => {
    await page.goto(`${BASE_URL}/admin/families?q=${encodeURIComponent(DEMO_USER.email)}`);
    await page.waitForLoadState('networkidle');
    const link = page.locator('table tbody tr a[href^="/admin/families/"]').first();
    test.skip(
      (await link.count()) === 0,
      `no family matches ${DEMO_USER.email} on this deployment`
    );
    await page.goto(`${BASE_URL}${await link.getAttribute('href')}`);
    await page.waitForLoadState('networkidle');

    // "restore default (all on)" writes enabled_modules = NULL. Picked over
    // comp-plus / suspend on purpose: it is the one bounded action that leaves
    // the e2e tenant in the state every OTHER spec already assumes (all modules
    // on), so running this suite can never switch /budget or /gigs off for the
    // specs that run after it.
    const reason = `e2e audit probe ${Date.now()}`;
    // Every operator action prompts for a reason before it fires; an unhandled
    // prompt is auto-dismissed by Playwright and submitAction would bail.
    page.on('dialog', (d) => d.accept(reason));

    const form = page.locator('form[data-action$="/modules"]');
    await expect(form).toBeVisible();
    await form.locator('input[name="__null_modules"]').check();

    const posted = page.waitForResponse(
      (r) => r.url().includes('/modules') && r.request().method() === 'POST'
    );
    await form.getByRole('button', { name: 'Save modules' }).click();
    expect((await posted).status()).toBe(200);

    // submitAction reloads the page on success.
    await page.waitForLoadState('networkidle');
    await expect(page.getByText('all modules on (default)')).toBeVisible();

    // The trail is append-only and filterable by action. Columns:
    // When | Operator | Action | Family | Result | Params (admin/audit.astro).
    await page.goto(`${BASE_URL}/admin/audit?action=family.set_modules`);
    await page.waitForLoadState('networkidle');
    const entry = page.locator('table tbody tr', { hasText: reason });
    await expect(entry).toHaveCount(1);
    await expect(entry.locator('td').nth(1)).toHaveText(OPERATOR_USER.email);
    await expect(entry.locator('td').nth(2)).toHaveText('family.set_modules');
    await expect(entry.locator('td').nth(4)).toContainText('ok');
  });
});
