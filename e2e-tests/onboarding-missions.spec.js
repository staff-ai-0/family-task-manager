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

// Mission 2 ("first-gig") reachability: buildMission("first-gig"), the gig
// anchors/signals, and the resume blocks all exist, but the mission is only
// useful if arming it actually runs it. This seeds the armed state (the same
// sessionStorage key the checklist launcher + first-task completion chain set)
// and confirms the resume block on parent/gigs.astro picks it up and highlights
// the gig FAB. We arm directly rather than clicking the checklist launcher
// because that launcher is (correctly) hidden once the family has any gig —
// gig_created is derived on read — and the demo family already has gigs.
test('first-gig mission runs when armed (resume block on /parent/gigs)', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE_URL}/parent/gigs`);
  await page.evaluate(() => sessionStorage.setItem('ftm_mission_first-gig', '0'));
  await page.goto(`${BASE_URL}/parent/gigs`);
  await page.waitForLoadState('networkidle');
  // Step 1 of the first-gig mission highlights the gig FAB.
  await expect(page.locator('.driver-popover')).toBeVisible({ timeout: 5000 });
});

// Mission 2 ("first-gig") support: the parent gig-create form (parent/gigs.astro)
// now carries a payout_cadence select alongside the gig-fab/gig-cadence/gig-submit
// data-tour hooks and dispatches the matching ftm:mission signals. This test
// doesn't drive the mission popover itself (covered by the pattern above) — it
// verifies the real, non-mission behavior the mission's steps are anchored to:
// the cadence value picked in the UI actually round-trips through the
// POST /api/gigs/offerings body and persists.
test('gig form posts payout_cadence and it persists', async ({ page }) => {
  await login(page);
  await page.goto(`${BASE_URL}/gigs`);
  await page.click('[data-tour="gig-fab"]');
  await page.fill('input[name="title"], #gig-title', 'Lavar el coche');
  await page.fill('input[name="points"], #gig-points', '50');
  await page.selectOption('[data-tour="gig-cadence"]', 'weekly');
  await page.click('[data-tour="gig-submit"]');
  // The new gig card renders; reload and confirm the cadence stuck via API.
  // GET /api/gigs/offerings returns EnrichedOfferingResponse rows
  // ({ offering, my_claim, active_claimers }), not flat offerings — same
  // `item.offering ?? item` unwrap parent/gigs.astro's frontmatter uses.
  const resp = await page.request.get(`${BASE_URL}/api/gigs/offerings`);
  const offerings = await resp.json();
  expect(offerings.some((o) => (o.offering ?? o).payout_cadence === 'weekly')).toBeTruthy();
});
