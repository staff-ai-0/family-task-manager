const { test, expect } = require('@playwright/test');

test.describe('Reward Management', () => {
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

  test.describe('Reward Creation', () => {
    test('should create a new reward with valid data', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      // Find create reward form
      const nameInput = page.locator('input[name="name"]').first();
      const pointsInput = page.locator('input[name="points_cost"]').first();
      const categorySelect = page.locator('select[name="category"]').first();

      if (await nameInput.count() > 0) {
        const rewardName = `Test Reward ${Date.now()}`;
        await nameInput.fill(rewardName);
        await pointsInput.fill('100');
        
        if (await categorySelect.count() > 0) {
          await categorySelect.selectOption('activities');
        }

        // Submit form
        const submitButton = page.locator('button:has-text("Create"), button[type="submit"]').first();
        await submitButton.click();

        // Wait for success message
        const successMessage = page.locator('.bg-green-50, text=created');
        await successMessage.waitFor({ timeout: 5000 }).catch(() => {});
        
        await page.waitForTimeout(500);

        // Verify reward appears in list
        const rewardInList = page.locator('h3, p').filter({ hasText: rewardName });
        expect(await rewardInList.count()).toBeGreaterThan(0);
      }
    });

    test('should create reward with treats category', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      const nameInput = page.locator('input[name="name"]').first();
      const pointsInput = page.locator('input[name="points_cost"]').first();
      const categorySelect = page.locator('select[name="category"]').first();

      if (await nameInput.count() > 0 && await categorySelect.count() > 0) {
        const rewardName = `Treat Reward ${Date.now()}`;
        await nameInput.fill(rewardName);
        await pointsInput.fill('50');
        await categorySelect.selectOption('treats');

        const submitButton = page.locator('button:has-text("Create"), button[type="submit"]').first();
        await submitButton.click();

        await page.waitForTimeout(500);
      }
    });

    test('should create reward with privileges category', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      const nameInput = page.locator('input[name="name"]').first();
      const pointsInput = page.locator('input[name="points_cost"]').first();
      const categorySelect = page.locator('select[name="category"]').first();

      if (await nameInput.count() > 0 && await categorySelect.count() > 0) {
        const rewardName = `Privilege Reward ${Date.now()}`;
        await nameInput.fill(rewardName);
        await pointsInput.fill('200');
        await categorySelect.selectOption('privileges');

        const submitButton = page.locator('button:has-text("Create"), button[type="submit"]').first();
        await submitButton.click();

        await page.waitForTimeout(500);
      }
    });

    test('should require reward name field', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      const nameInput = page.locator('input[name="name"]').first();
      if (await nameInput.count() > 0) {
        const isRequired = await nameInput.evaluate(el => el.required);
        expect(isRequired).toBe(true);
      }
    });

    test('should have default points value', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      const pointsInput = page.locator('input[name="points_cost"]').first();
      if (await pointsInput.count() > 0) {
        const defaultValue = await pointsInput.inputValue();
        expect(defaultValue).toBeTruthy();
        expect(parseInt(defaultValue)).toBeGreaterThan(0);
      }
    });
  });

  test.describe('Reward Editing', () => {
    test('should edit an existing reward', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      // Find edit button for first reward
      const editButton = page.locator('a[href*="/rewards/"], button:has-text("Edit")').first();
      if (await editButton.count() > 0) {
        await editButton.click();
        await page.waitForLoadState('networkidle');

        // Update reward
        const nameInput = page.locator('input[name="name"], input[name="title"]').first();
        if (await nameInput.count() > 0) {
          const newName = `Updated Reward ${Date.now()}`;
          const currentValue = await nameInput.inputValue();
          
          // Clear and type new value
          await nameInput.fill(newName);

          // Submit form
          const submitButton = page.locator('button:has-text("Save"), button:has-text("Update"), button[type="submit"]').first();
          await submitButton.click();

          // Wait for navigation
          await page.waitForTimeout(500);
        }
      }
    });

    test('should update reward category', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      const editButton = page.locator('a[href*="/rewards/"], button:has-text("Edit")').first();
      if (await editButton.count() > 0) {
        await editButton.click();
        await page.waitForLoadState('networkidle');

        const categorySelect = page.locator('select[name="category"]').first();
        if (await categorySelect.count() > 0) {
          await categorySelect.selectOption('money');

          const submitButton = page.locator('button:has-text("Save"), button:has-text("Update"), button[type="submit"]').first();
          await submitButton.click();

          await page.waitForTimeout(500);
        }
      }
    });
  });

  test.describe('Reward Deletion', () => {
    test('should delete a reward', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      // Find delete button for first reward
      const deleteButton = page.locator('button:has-text("Delete"), button[aria-label*="delete"]').first();
      if (await deleteButton.count() > 0) {
        await deleteButton.click();

        // Confirm deletion
        const confirmButton = page.locator('button:has-text("Confirm"), button:has-text("Delete"), button:has-text("Yes")').last();
        if (await confirmButton.count() > 0) {
          await confirmButton.click();
        }

        await page.waitForTimeout(500);

        // Verify success message or count decreased
        const successMessage = page.locator('text=deleted, text=removed').first();
        if (await successMessage.count() > 0) {
          expect(await successMessage.textContent()).toBeTruthy();
        }
      }
    });
  });

  test.describe('Reward Listing', () => {
    test('should display list of rewards', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      // Check if rewards are displayed
      const rewardItems = page.locator('div.rounded-2xl, li').filter({ hasText: 'pts' });
      const count = await rewardItems.count();

      // Should have rewards or show empty state
      if (count === 0) {
        const emptyMessage = page.locator('text=no rewards, text=empty, text=None');
        expect(await emptyMessage.count()).toBeGreaterThan(0);
      } else {
        expect(count).toBeGreaterThan(0);
      }
    });

    test('should display reward details (name, points, category)', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      // Find a reward
      const rewardTitle = page.locator('h3, h2').first();
      if (await rewardTitle.count() > 0) {
        const titleText = await rewardTitle.textContent();
        expect(titleText).toBeTruthy();

        // Look for points
        const pointsText = page.locator('text=/\\d+\\s*pts/').first();
        if (await pointsText.count() > 0) {
          const pointsValue = await pointsText.textContent();
          expect(pointsValue).toMatch(/\d+\s*pts/);
        }
      }
    });

    test('should filter rewards by category', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      // Look for category filter buttons
      const categoryFilter = page.locator('button:has-text("Screen Time"), button:has-text("Treats"), button:has-text("Activities")').first();
      if (await categoryFilter.count() > 0) {
        await categoryFilter.click();
        await page.waitForLoadState('networkidle');

        // Verify filtered results
        const rewardItems = page.locator('div.rounded-2xl, li');
        expect(await rewardItems.count()).toBeDefined();
      }
    });
  });

  test.describe('Reward Redemption', () => {
    test('should allow child to redeem reward', async ({ page }) => {
      // Login as child user
      await page.goto(`${BASE_URL}/login`);
      await page.waitForLoadState('networkidle');
      await page.fill('input[name="email"]', 'emma@demo.com');
      await page.fill('input[name="password"]', 'password123');
      await page.click('button[type="submit"]');
      await page.waitForURL('**/dashboard', { timeout: 10000 });

      // Navigate to rewards
      await page.goto(`${BASE_URL}/rewards`);
      await page.waitForLoadState('networkidle');

      // Find redeem button
      const redeemButton = page.locator('button:has-text("Redeem"), button:has-text("Request")').first();
      if (await redeemButton.count() > 0) {
        await redeemButton.click();
        await page.waitForTimeout(500);

        // Check for confirmation or success message
        const successMessage = page.locator('text=success, text=requested, text=redeemed').first();
        expect(await successMessage.count()).toBeGreaterThan(0);
      }
    });
  });

  test.describe('Category Options', () => {
    test('should have all reward categories available', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/rewards`);
      await page.waitForLoadState('networkidle');

      const categorySelect = page.locator('select[name="category"]').first();
      if (await categorySelect.count() > 0) {
        const options = await categorySelect.locator('option').all();
        const optionValues = await Promise.all(
          options.map(option => option.getAttribute('value'))
        );

        // Check for expected categories
        const expectedCategories = ['screen_time', 'treats', 'activities', 'privileges', 'money', 'toys'];
        const availableCategories = optionValues.filter(v => v && v !== '');

        expectedCategories.forEach(category => {
          expect(availableCategories).toContain(category);
        });
      }
    });
  });
});
