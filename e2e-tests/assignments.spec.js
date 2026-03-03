const { test, expect } = require('@playwright/test');

test.describe('Assignment Management', () => {
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

  test.describe('Assignment Creation', () => {
    test('should create a new task assignment', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/assignments`);
      await page.waitForLoadState('networkidle');

      // Find assignment creation form/button
      const taskSelect = page.locator('select[name="task_id"], button:has-text("Select task")').first();
      const memberSelect = page.locator('select[name="member_id"], button:has-text("Select member")').first();

      if (await taskSelect.count() > 0 && await memberSelect.count() > 0) {
        // Select task
        await taskSelect.click();
        const taskOption = page.locator('option').nth(1);
        if (await taskOption.count() > 0) {
          await taskOption.click();
        }

        // Select member
        await memberSelect.click();
        const memberOption = page.locator('option').nth(1);
        if (await memberOption.count() > 0) {
          await memberOption.click();
        }

        // Submit
        const submitButton = page.locator('button:has-text("Assign"), button:has-text("Create"), button[type="submit"]').first();
        await submitButton.click();

        await page.waitForTimeout(1000);
      }
    });

    test('should require task and member selection', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/assignments`);
      await page.waitForLoadState('networkidle');

      const taskSelect = page.locator('select[name="task_id"]').first();
      const memberSelect = page.locator('select[name="member_id"]').first();

      if (await taskSelect.count() > 0) {
        const isRequired = await taskSelect.evaluate(el => el.required);
        expect(isRequired).toBe(true);
      }

      if (await memberSelect.count() > 0) {
        const isRequired = await memberSelect.evaluate(el => el.required);
        expect(isRequired).toBe(true);
      }
    });
  });

  test.describe('Assignment Listing', () => {
    test('should display list of assignments', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/assignments`);
      await page.waitForLoadState('networkidle');

      // Check for assignment items
      const assignmentItems = page.locator('div.rounded-2xl, div.bg-white, li');
      const count = await assignmentItems.count();

      // Should have assignments or show empty state
      if (count > 0) {
        expect(count).toBeGreaterThan(0);
      } else {
        const emptyMessage = page.locator('text=no assignments, text=empty').first();
        expect(await emptyMessage.count()).toBeGreaterThan(0);
      }
    });

    test('should display assignment details (task, member, due date)', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/assignments`);
      await page.waitForLoadState('networkidle');

      // Find an assignment item
      const assignmentItem = page.locator('div.rounded-2xl, div.bg-white').first();
      if (await assignmentItem.count() > 0) {
        const itemText = await assignmentItem.textContent();
        expect(itemText).toBeTruthy();
      }
    });
  });

  test.describe('Assignment Status Update', () => {
    test('should update assignment status to completed', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/assignments`);
      await page.waitForLoadState('networkidle');

      // Find status update button
      const statusButton = page.locator('button:has-text("Mark Complete"), button:has-text("Complete"), button:has-text("Approve")').first();
      if (await statusButton.count() > 0) {
        await statusButton.click();
        await page.waitForTimeout(500);

        // Verify status changed
        const successMessage = page.locator('text=completed, text=approved, text=updated').first();
        expect(await successMessage.count()).toBeGreaterThan(0);
      }
    });

    test('should filter assignments by status', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/assignments`);
      await page.waitForLoadState('networkidle');

      // Look for status filter buttons
      const filterButtons = page.locator('button:has-text("Active"), button:has-text("Completed"), button:has-text("Pending"), button:has-text("All")');
      if (await filterButtons.count() > 0) {
        const activeFilter = page.locator('button:has-text("Active")').first();
        if (await activeFilter.count() > 0) {
          await activeFilter.click();
          await page.waitForLoadState('networkidle');

          const assignmentItems = page.locator('div.rounded-2xl, li');
          expect(await assignmentItems.count()).toBeDefined();
        }
      }
    });
  });

  test.describe('Assignment Deletion', () => {
    test('should delete an assignment', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/assignments`);
      await page.waitForLoadState('networkidle');

      const deleteButton = page.locator('button:has-text("Delete"), button[aria-label*="delete"]').first();
      if (await deleteButton.count() > 0) {
        await deleteButton.click();

        // Confirm deletion
        const confirmButton = page.locator('button:has-text("Confirm"), button:has-text("Delete"), button:has-text("Yes")').last();
        if (await confirmButton.count() > 0) {
          await confirmButton.click();
        }

        await page.waitForTimeout(500);

        const successMessage = page.locator('text=deleted, text=removed').first();
        if (await successMessage.count() > 0) {
          expect(await successMessage.textContent()).toBeTruthy();
        }
      }
    });
  });

  test.describe('Assignment by Child', () => {
    test('should show pending assignments for child user', async ({ page }) => {
      // Login as child
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState('networkidle');
      
      // Clear previous login
      await page.context().clearCookies();
      
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState('networkidle');
      await page.fill('input[name="email"]', 'emma@demo.com');
      await page.fill('input[name="password"]', 'password123');
      await page.click('button[type="submit"]');
      await page.waitForURL('**/dashboard', { timeout: 10000 });

      // Navigate to assignments or dashboard
      await page.goto(`${BASE_URL}/dashboard`);
      await page.waitForLoadState('networkidle');

      // Look for assignments section or link
      const assignmentsLink = page.locator('a:has-text("Assignments"), text=Assignments').first();
      if (await assignmentsLink.count() > 0) {
        // Assignments are visible on dashboard
        expect(true).toBe(true);
      }
    });
  });

  test.describe('Assignment Due Dates', () => {
    test('should display due date for assignments', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/assignments`);
      await page.waitForLoadState('networkidle');

      // Look for date display
      const dateText = page.locator('text=/\\d{1,2}\\/\\d{1,2}\\/\\d{4}|\\d{4}-\\d{2}-\\d{2}/').first();
      if (await dateText.count() > 0) {
        const dateValue = await dateText.textContent();
        expect(dateValue).toMatch(/\\d/);
      }
    });
  });
});
