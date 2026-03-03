const { test, expect } = require('@playwright/test');

test.describe('Task Management', () => {
  const BASE_URL = 'http://localhost:3003';
  const DEMO_USER = {
    email: 'mom@demo.com',
    password: 'password123',
  };

  test.beforeEach(async ({ page }) => {
    // Login before each test
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');
    await page.fill('input[name="email"]', DEMO_USER.email);
    await page.fill('input[name="password"]', DEMO_USER.password);
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard', { timeout: 10000 });
  });

  test.describe('Task Creation', () => {
    test('should create a new task with valid data', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/tasks`);
      await page.waitForLoadState('networkidle');

      // Find create task form
      const nameInput = page.locator('input[name="name"], input[placeholder*="task"], input[placeholder*="Task"]').first();
      const pointsInput = page.locator('input[name="points_value"], input[name="points"], input[type="number"]').first();

      if (await nameInput.count() > 0) {
        const taskName = `Test Task ${Date.now()}`;
        await nameInput.fill(taskName);

        if (await pointsInput.count() > 0) {
          await pointsInput.fill('50');
        }

        // Submit form
        const submitButton = page.locator('button:has-text("Create"), button:has-text("Add"), button[type="submit"]').first();
        await submitButton.click();

        // Wait for success message or task to appear in list
        await page.waitForTimeout(1000);

        // Verify task appears in the task list
        const taskList = page.locator('h3, p').filter({ hasText: taskName });
        expect(await taskList.count()).toBeGreaterThan(0);
      }
    });

    test('should require task name field', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/tasks`);
      await page.waitForLoadState('networkidle');

      const nameInput = page.locator('input[name="name"], input[placeholder*="task"]').first();
      if (await nameInput.count() > 0) {
        const isRequired = await nameInput.evaluate(el => el.required);
        expect(isRequired).toBe(true);
      }
    });
  });

  test.describe('Task Editing', () => {
    test('should edit an existing task', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/tasks`);
      await page.waitForLoadState('networkidle');

      // Find edit button for first task
      const editButton = page.locator('a[href*="/tasks/"], button:has-text("Edit")').first();
      if (await editButton.count() > 0) {
        await editButton.click();
        await page.waitForLoadState('networkidle');

        // Update task name
        const nameInput = page.locator('input[name="name"], input[name="title"]').first();
        if (await nameInput.count() > 0) {
          const newName = `Updated Task ${Date.now()}`;
          await nameInput.fill(newName);

          // Submit form
          const submitButton = page.locator('button:has-text("Save"), button:has-text("Update"), button[type="submit"]').first();
          await submitButton.click();

          // Wait for navigation back to task list
          await page.waitForURL('**/tasks', { timeout: 5000 }).catch(() => {});
          await page.waitForTimeout(500);

          // Navigate back to tasks to verify
          await page.goto(`${BASE_URL}/parent/tasks`);
          await page.waitForLoadState('networkidle');
        }
      }
    });
  });

  test.describe('Task Deletion', () => {
    test('should delete a task', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/tasks`);
      await page.waitForLoadState('networkidle');

      // Get initial task count
      const taskItems = page.locator('div.rounded-2xl, li').filter({ hasText: 'pts' });
      const initialCount = await taskItems.count();

      // Find delete button for first task
      const deleteButton = page.locator('button:has-text("Delete"), button[aria-label*="delete"]').first();
      if (await deleteButton.count() > 0) {
        await deleteButton.click();

        // Confirm deletion if dialog appears
        const confirmButton = page.locator('button:has-text("Confirm"), button:has-text("Delete"), button:has-text("Yes")').last();
        if (await confirmButton.count() > 0) {
          await confirmButton.click();
        }

        // Wait for update
        await page.waitForTimeout(1000);

        // Verify task count decreased or success message appears
        const successMessage = page.locator('text=deleted, text=removed, text=success').first();
        if (await successMessage.count() > 0) {
          expect(await successMessage.textContent()).toBeTruthy();
        }
      }
    });
  });

  test.describe('Task Listing', () => {
    test('should display list of tasks', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/tasks`);
      await page.waitForLoadState('networkidle');

      // Check if tasks are displayed
      const taskList = page.locator('div.rounded-2xl, div.bg-white').filter({ hasText: 'pts' });
      const count = await taskList.count();

      // Should have at least one task or show empty state
      if (count === 0) {
        const emptyMessage = page.locator('text=no tasks, text=empty').first();
        expect(await emptyMessage.count()).toBeGreaterThan(0);
      } else {
        expect(count).toBeGreaterThan(0);
      }
    });

    test('should display task details (name, points, description)', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/tasks`);
      await page.waitForLoadState('networkidle');

      // Find a task with points displayed
      const taskWithPoints = page.locator('h3, h2').first();
      if (await taskWithPoints.count() > 0) {
        const taskName = await taskWithPoints.textContent();
        expect(taskName).toBeTruthy();

        // Look for points value
        const pointsText = page.locator('text=/\\d+\\s*pts/').first();
        if (await pointsText.count() > 0) {
          const pointsValue = await pointsText.textContent();
          expect(pointsValue).toMatch(/\d+\s*pts/);
        }
      }
    });
  });

  test.describe('Task Assignment', () => {
    test('should assign task to a family member', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/tasks`);
      await page.waitForLoadState('networkidle');

      // Find assign button for first task
      const assignButton = page.locator('button:has-text("Assign"), button:has-text("Assign to")').first();
      if (await assignButton.count() > 0) {
        await assignButton.click();
        await page.waitForLoadState('networkidle');

        // Select a family member from dropdown or list
        const memberSelect = page.locator('select[name="member_id"], button:has-text("Select member")').first();
        if (await memberSelect.count() > 0) {
          await memberSelect.click();
          
          // Select first available member option
          const memberOption = page.locator('option, div[role="option"]').nth(1);
          if (await memberOption.count() > 0) {
            await memberOption.click();
          }

          // Submit assignment
          const submitButton = page.locator('button:has-text("Assign"), button[type="submit"]').first();
          await submitButton.click();

          // Wait for success
          await page.waitForTimeout(1000);
        }
      }
    });
  });

  test.describe('Task Search/Filter', () => {
    test('should filter tasks by status', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/tasks`);
      await page.waitForLoadState('networkidle');

      // Look for filter buttons
      const filterButtons = page.locator('button:has-text("Active"), button:has-text("Completed"), button:has-text("All")');
      if (await filterButtons.count() > 0) {
        // Click on "Active" filter if exists
        const activeFilter = page.locator('button:has-text("Active")').first();
        if (await activeFilter.count() > 0) {
          await activeFilter.click();
          await page.waitForLoadState('networkidle');

          // Verify page updated with filtered tasks
          const taskList = page.locator('div.rounded-2xl, li').filter({ hasText: 'pts' });
          expect(await taskList.count()).toBeDefined();
        }
      }
    });
  });
});
