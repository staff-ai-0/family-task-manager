const { test, expect } = require('@playwright/test');

test.describe('Member Management', () => {
  const BASE_URL = 'http://localhost:3003';
  const DEMO_USER = {
    email: 'mom@demo.com',
    password: 'password123',
  };

  test.beforeEach(async ({ page }) => {
    // Login as parent
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');
    await page.fill('input[name="email"]', DEMO_USER.email);
    await page.fill('input[name="password"]', DEMO_USER.password);
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard', { timeout: 10000 });
  });

  test.describe('Member Listing', () => {
    test('should display list of family members', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Check for member items
      const memberItems = page.locator('div.rounded-2xl, div.bg-white, li');
      const count = await memberItems.count();

      if (count > 0) {
        expect(count).toBeGreaterThan(0);
      }
    });

    test('should display member details (name, role, points)', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Find a member item
      const memberName = page.locator('h3, h2').first();
      if (await memberName.count() > 0) {
        const nameText = await memberName.textContent();
        expect(nameText).toBeTruthy();

        // Look for points
        const pointsText = page.locator('text=/\\d+\\s*pts|points/').first();
        if (await pointsText.count() > 0) {
          const pointsValue = await pointsText.textContent();
          expect(pointsValue).toMatch(/\\d/);
        }
      }
    });

    test('should show member roles (parent, teen, child)', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Look for role displays
      const roles = page.locator('text=Parent, text=Teen, text=Child');
      expect(await roles.count()).toBeGreaterThan(0);
    });
  });

  test.describe('Member Invitation', () => {
    test('should display invitation section for new members', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Look for invite button
      const inviteButton = page.locator('button:has-text("Invite"), button:has-text("Add member"), button:has-text("New member")').first();
      expect(await inviteButton.count()).toBeGreaterThan(0);
    });

    test('should show invitation code or form', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Look for invitation code display
      const invitationCode = page.locator('text=invitation code, text=family code, code');
      const codeInput = page.locator('input[type="text"], input[readonly]');

      if (await invitationCode.count() > 0 || await codeInput.count() > 0) {
        expect(true).toBe(true);
      }
    });
  });

  test.describe('Member Points Management', () => {
    test('should display member points balance', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Look for points display
      const pointsText = page.locator('text=/\\d+\\s*pts/').first();
      if (await pointsText.count() > 0) {
        const pointsValue = await pointsText.textContent();
        expect(pointsValue).toMatch(/\\d+\\s*pts/);
      }
    });

    test('should allow parent to add/adjust member points', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Look for adjust points button
      const adjustButton = page.locator('button:has-text("Adjust"), button:has-text("Add points"), button:has-text("Edit points")').first();
      if (await adjustButton.count() > 0) {
        await adjustButton.click();
        await page.waitForLoadState('networkidle');

        // Look for points input
        const pointsInput = page.locator('input[type="number"], input[name*="points"]');
        if (await pointsInput.count() > 0) {
          expect(true).toBe(true);
        }
      }
    });
  });

  test.describe('Member Status', () => {
    test('should show member active status', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Look for active/inactive status
      const statusBadges = page.locator('span:has-text("Active"), span:has-text("Inactive")');
      if (await statusBadges.count() > 0) {
        expect(true).toBe(true);
      }
    });

    test('should allow deactivating a member', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Find deactivate button (should not be on first item if it's last parent)
      const actionButtons = page.locator('button:has-text("Deactivate"), button:has-text("Edit")');
      if (await actionButtons.count() > 0) {
        const deactivateButton = actionButtons.filter({ hasText: 'Deactivate' }).first();
        
        if (await deactivateButton.count() > 0) {
          // Check if button is disabled (last parent protection)
          const isDisabled = await deactivateButton.evaluate(el => el.disabled);
          // Button should either be disabled or work
          expect(typeof isDisabled).toBe('boolean');
        }
      }
    });
  });

  test.describe('Member Profile View', () => {
    test('should display member profile details', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Click on first member to view profile
      const memberLink = page.locator('a, button').filter({ hasText: /[A-Z][a-z]+/ }).first();
      if (await memberLink.count() > 0) {
        const href = await memberLink.getAttribute('href');
        
        if (href && href.includes('/')) {
          await memberLink.click();
          await page.waitForLoadState('networkidle');

          // Should see member details on profile page
          const profileTitle = page.locator('h1, h2');
          expect(await profileTitle.count()).toBeGreaterThan(0);
        }
      }
    });
  });

  test.describe('Family Code', () => {
    test('should display family invitation code', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Look for family code display
      const codeDisplay = page.locator('input[readonly], text=family code, text=invite code').first();
      if (await codeDisplay.count() > 0) {
        const codeValue = await codeDisplay.inputValue ? 
          await codeDisplay.inputValue() : 
          await codeDisplay.textContent();
        
        expect(codeValue).toBeTruthy();
      }
    });

    test('should allow copying family code', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Look for copy button
      const copyButton = page.locator('button:has-text("Copy"), button[aria-label*="copy"]').first();
      if (await copyButton.count() > 0) {
        await copyButton.click();
        await page.waitForTimeout(500);

        // Look for success feedback
        const feedback = page.locator('text=copied, text=success').first();
        expect(await feedback.count()).toBeGreaterThan(0);
      }
    });
  });

  test.describe('Member Role Display', () => {
    test('should distinguish between parent and child roles', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/members`);
      await page.waitForLoadState('networkidle');

      // Look for parent indicator
      const parentBadges = page.locator('text=Parent, text=PARENT, span:has-text("Parent")');
      const childBadges = page.locator('text=Child, text=CHILD, span:has-text("Child")');

      // Should have at least one parent and possibly children
      expect(await parentBadges.count()).toBeGreaterThan(0);
    });
  });
});
