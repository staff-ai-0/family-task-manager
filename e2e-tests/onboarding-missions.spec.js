const { test, expect } = require('@playwright/test');

/**
 * Action-driven onboarding "mission" runner (missionRunner.ts) — Mission 1
 * ("first-task"). Unlike the passive driver.js welcome tour, a mission step
 * only advances on a REAL ftm:mission signal (task-modal-open,
 * task-template-selected, task-assignee-selected, task-created), dispatched
 * by tasks.astro / TaskCreateModal.astro at each real milestone. Degrades
 * gracefully (no dead end) when a step's target isn't on the current page.
 *
 * Requires the dev stack on :3003 with the current build + seeded demo data.
 */
const BASE_URL = process.env.BASE_URL || 'http://localhost:3003';

async function login(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', 'mom@demo.com');
  await page.fill('input[name="password"]', 'password123');
  await page.click('#login-submit-btn');
  await page.waitForURL('**/dashboard', { timeout: 30000 });
}

test('mission 1 advances when the task modal actually opens', async ({ page }) => {
  await login(page);
  await page.evaluate(() => sessionStorage.setItem('ftm_mission_first-task', '0'));
  await page.goto(`${BASE_URL}/parent/tasks`);
  // Step 1 highlights the FAB.
  await expect(page.locator('.driver-popover')).toBeVisible({ timeout: 5000 });
  // Perform the REAL action — open the modal — and the mission should advance
  // to the template step (not wait for a Next button).
  await page.click('[data-tour="task-fab"]');
  await expect(page.locator('.driver-popover')).toContainText(/plantilla|template|chore|tarea/i, { timeout: 5000 });
});

test('mission target absent → no dead end (popover closes gracefully)', async ({ page }) => {
  await login(page);
  await page.evaluate(() => sessionStorage.setItem('ftm_mission_first-task', '3'));
  // Land on a page WITHOUT the submit target present standalone.
  await page.goto(`${BASE_URL}/dashboard`);
  // Runner finds no element for step 3 here and ends without throwing.
  await expect(page.locator('.driver-popover')).toHaveCount(0, { timeout: 5000 });
});

test('mission target present but CSS-hidden → degrades cleanly, never highlighted', async ({ page }) => {
  await login(page);
  // Step index 1 targets '[data-tour="task-template-grid"]', which lives
  // inside TaskCreateModal.astro — always rendered in the DOM, but behind
  // a "hidden" (display:none) class until the + FAB opens it. A
  // DOM-presence-only check would find it and highlight nothing-visible;
  // the runner must treat "present but not visible" the same as "absent".
  await page.evaluate(() => sessionStorage.setItem('ftm_mission_first-task', '1'));
  await page.goto(`${BASE_URL}/parent/tasks`);
  await expect(page.locator('.driver-popover')).toHaveCount(0, { timeout: 5000 });
});
