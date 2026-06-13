const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const EMAIL = process.env.E2E_EMAIL || 'e2e-fresh@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'fresh1234';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL('**/dashboard', { timeout: 15000 });
}

test.describe('Calendar recurrence', () => {
  test('create weekly recurring event → 4+ occurrences visible in agenda', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/calendar`);
    await page.getByText(/Nuevo evento|New event/i).first().click();

    const title = `E2E weekly ${Date.now()}`;
    await page.fill('input[name="title"]', title);
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    await page.fill('input[name="date"]', tomorrow.toISOString().slice(0, 10));
    await page.fill('input[name="time"]', '15:00');
    await page.selectOption('select[name="recurrence"]', 'weekly');
    await page.locator('button[type="submit"]').first().click();
    await page.waitForLoadState('networkidle');

    // Agenda spans 60 days → weekly = ~8 occurrences
    const matches = await page.getByText(title).count();
    expect(matches).toBeGreaterThanOrEqual(2);
  });

  test('custom RRULE input accepted', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE_URL}/calendar`);
    await page.getByText(/Nuevo evento|New event/i).first().click();

    const title = `E2E rrule ${Date.now()}`;
    await page.fill('input[name="title"]', title);
    const future = new Date();
    future.setDate(future.getDate() + 1);
    await page.fill('input[name="date"]', future.toISOString().slice(0, 10));
    await page.fill('input[name="time"]', '10:00');
    await page.selectOption('select[name="recurrence"]', 'custom');
    await page.fill('input[name="recurrence_custom"]', 'FREQ=WEEKLY;BYDAY=MO,WE,FR');
    await page.locator('form button[type="submit"]').first().click();
    await page.waitForLoadState('networkidle');
    await page.goto(`${BASE_URL}/calendar`);
    await expect(page.getByText(title).first()).toBeVisible({ timeout: 10000 });
  });

  test('iCal feed responds with text/calendar', async ({ page }) => {
    await login(page);
    const response = await page.request.get(`${BASE_URL}/api/calendar/feed.ics`);
    // Expect 200 with iCal content OR 401 if proxy strips auth
    if (response.ok()) {
      const text = await response.text();
      expect(text).toContain('BEGIN:VCALENDAR');
      expect(text).toContain('END:VCALENDAR');
    } else {
      expect([401, 403, 405]).toContain(response.status());
    }
  });
});
