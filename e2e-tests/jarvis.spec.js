const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';
const EMAIL = process.env.E2E_EMAIL || 'e2e-fresh@example.com';
const PASSWORD = process.env.E2E_PASSWORD || 'fresh1234';
// e2e-fresh is on Plus (other specs — jarvis-schedules, scanner-v2 — need
// AI-gated pages to render for real, not the upsell screen). This gating
// test needs a genuinely unsubscribed account instead (backend/seed_data.py).
const FREE_EMAIL = process.env.E2E_FREE_EMAIL || 'e2e-free@example.com';
const FREE_PASSWORD = process.env.E2E_FREE_PASSWORD || 'free1234';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', EMAIL);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('#login-submit-btn');
  await page.waitForURL('**/dashboard', { timeout: 30000 });
}

async function loginFree(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', FREE_EMAIL);
  await page.fill('input[name="password"]', FREE_PASSWORD);
  await page.click('#login-submit-btn');
  await page.waitForURL('**/dashboard', { timeout: 30000 });
}

test.describe('Jarvis copilot', () => {
  test('free-plan parent sees upsell instead of chat input', async ({ page }) => {
    // e2e-free has no subscription → free plan → Jarvis is paid-only.
    await loginFree(page);
    await page.goto(`${BASE_URL}/parent/jarvis`);
    await expect(page.locator('h1')).toContainText('Jarvis');
    await expect(page.locator('a[href*="subscription"]')).toBeVisible();
    await expect(page.locator('#message-input')).toBeHidden();
  });

  test('plus-plan parent can open chat page and see input', async ({ page }) => {
    await loginDemo(page);
    await page.goto(`${BASE_URL}/parent/jarvis`);
    await expect(page.locator('h1')).toContainText('Jarvis');
    await expect(page.locator('#message-input')).toBeVisible();
  });

  test('sends a message and gets a response or graceful error', async ({ page }) => {
    test.skip(!process.env.E2E_FULL, 'requires LITELLM_API_KEY in backend');
    await login(page);
    await page.goto(`${BASE_URL}/parent/jarvis`);
    await page.fill('#message-input', 'What needs my attention today?');
    await page.locator('#chat-form button[type="submit"]').click();
    // Bot reply bubble appears within 30s, or alert pops with error
    await page.waitForTimeout(2000);
    const bubbles = page.locator('main .bg-brand-cream.border');
    await expect(bubbles).toHaveCount(2, { timeout: 30000 });
  });
});

// Error-UX regression suite for WK29 QA (Jesus, Jul 14): failures must render
// inline in the chat feed — never a browser alert() — and the user's text must
// survive for retry. Uses route interception so no LLM/backend failure setup
// is needed; demo mom is on the Plus plan so the chat form is visible.
const DEMO_EMAIL = 'mom@demo.com';
const DEMO_PASSWORD = 'password123';

async function loginDemo(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', DEMO_EMAIL);
  await page.fill('input[name="password"]', DEMO_PASSWORD);
  await page.click('#login-submit-btn');
  await page.waitForURL('**/dashboard', { timeout: 30000 });
}

test.describe('Jarvis chat error UX', () => {
  let dialogs;

  async function openChatWithRoute(page, fulfill) {
    dialogs = [];
    page.on('dialog', async (d) => { dialogs.push(d.message()); await d.dismiss(); });
    await loginDemo(page);
    await page.route('**/api/jarvis/chat-stream', (route) => route.fulfill(fulfill));
    await page.goto(`${BASE_URL}/parent/jarvis`);
    await page.fill('#message-input', 'hola jarvis');
    await page.click('#chat-form button[type="submit"]');
  }

  test('HTTP 500 renders inline error bubble, no alert, input restored', async ({ page }) => {
    await openChatWithRoute(page, {
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'LLM upstream exploded' }),
    });
    const bubble = page.locator('#chat-scroll [data-error-bubble]');
    await expect(bubble).toBeVisible({ timeout: 10000 });
    await expect(bubble).toContainText('LLM upstream exploded');
    expect(dialogs).toHaveLength(0);
    // Text survives for retry; the failed optimistic bubble is marked.
    await expect(page.locator('#message-input')).toHaveValue('hola jarvis');
    await expect(page.locator('#chat-scroll [data-send-failed]')).toHaveCount(1);
  });

  test('SSE error event renders inline error bubble, no alert', async ({ page }) => {
    await openChatWithRoute(page, {
      status: 200,
      contentType: 'text/event-stream',
      body: 'event: error\ndata: {"detail":"Jarvis failed: kaboom"}\n\n' +
            'event: done\ndata: {}\n\n',
    });
    const bubble = page.locator('#chat-scroll [data-error-bubble]');
    await expect(bubble).toBeVisible({ timeout: 10000 });
    await expect(bubble).toContainText('kaboom');
    expect(dialogs).toHaveLength(0);
    await expect(page.locator('#message-input')).toHaveValue('hola jarvis');
  });

  test('403 upgrade_required object never renders [object Object]', async ({ page }) => {
    await openChatWithRoute(page, {
      status: 403,
      contentType: 'application/json',
      body: JSON.stringify({ detail: {
        error: 'upgrade_required', feature: 'ai_features', plan_needed: 'plus',
        current_usage: 0, limit: 0,
        message: "The 'ai_features' feature requires a plus plan or higher.",
      } }),
    });
    const bubble = page.locator('#chat-scroll [data-error-bubble]');
    await expect(bubble).toBeVisible({ timeout: 10000 });
    await expect(bubble).not.toContainText('object Object');
    await expect(bubble).toContainText(/Plus/i);
    expect(dialogs).toHaveLength(0);
  });
});
