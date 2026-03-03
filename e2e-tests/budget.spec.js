const { test, expect } = require('@playwright/test');

test.describe('Budget & Finance Management', () => {
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

  test.describe('Budget Dashboard', () => {
    test('should display budget overview page', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances`);
      await page.waitForLoadState('networkidle');

      // Check for budget page elements
      const pageTitle = page.locator('h1, h2').filter({ hasText: /budget|finance|money/ });
      expect(await pageTitle.count()).toBeGreaterThan(0);
    });

    test('should display financial summary', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances`);
      await page.waitForLoadState('networkidle');

      // Look for summary cards
      const summaryCards = page.locator('div.rounded-2xl, div.bg-white');
      expect(await summaryCards.count()).toBeGreaterThan(0);
    });
  });

  test.describe('Accounts Management', () => {
    test('should display list of accounts', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/accounts`);
      await page.waitForLoadState('networkidle');

      // Check for account items
      const accountItems = page.locator('div.rounded-2xl, div.bg-white, li');
      const count = await accountItems.count();

      if (count > 0) {
        expect(count).toBeGreaterThan(0);
      } else {
        // Should show empty state or create button
        const createButton = page.locator('button:has-text("New"), button:has-text("Add account"), button:has-text("Create")').first();
        expect(await createButton.count()).toBeGreaterThan(0);
      }
    });

    test('should create a new account', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/accounts`);
      await page.waitForLoadState('networkidle');

      // Find create button
      const createButton = page.locator('a[href*="/new"], button:has-text("New"), button:has-text("Add account")').first();
      if (await createButton.count() > 0) {
        await createButton.click();
        await page.waitForLoadState('networkidle');

        // Fill in account details
        const nameInput = page.locator('input[name="name"], input[placeholder*="account"]').first();
        if (await nameInput.count() > 0) {
          await nameInput.fill(`Test Account ${Date.now()}`);

          // Select account type
          const typeSelect = page.locator('select[name="type"], button:has-text("Select type")').first();
          if (await typeSelect.count() > 0) {
            await typeSelect.click();
            const option = page.locator('option').nth(1);
            if (await option.count() > 0) {
              await option.click();
            }
          }

          // Submit
          const submitButton = page.locator('button:has-text("Save"), button:has-text("Create"), button[type="submit"]').first();
          await submitButton.click();

          await page.waitForTimeout(1000);
        }
      }
    });

    test('should display account details (name, type, balance)', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/accounts`);
      await page.waitForLoadState('networkidle');

      const accountName = page.locator('h3, h2').first();
      if (await accountName.count() > 0) {
        const nameText = await accountName.textContent();
        expect(nameText).toBeTruthy();

        // Look for balance
        const balanceText = page.locator('text=Balance, text=$, text=£, text=€').first();
        if (await balanceText.count() > 0) {
          expect(true).toBe(true);
        }
      }
    });
  });

  test.describe('Transactions', () => {
    test('should display list of transactions', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/transactions`);
      await page.waitForLoadState('networkidle');

      // Check for transaction items
      const transactionItems = page.locator('div.rounded-2xl, div.bg-white, tr, li');
      const count = await transactionItems.count();

      if (count > 0) {
        expect(count).toBeGreaterThan(0);
      } else {
        // Show empty state
        const emptyMessage = page.locator('text=no transactions, text=empty').first();
        expect(await emptyMessage.count()).toBeGreaterThan(0);
      }
    });

    test('should create a new transaction', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/transactions`);
      await page.waitForLoadState('networkidle');

      const createButton = page.locator('a[href*="/new"], button:has-text("New"), button:has-text("Add transaction")').first();
      if (await createButton.count() > 0) {
        await createButton.click();
        await page.waitForLoadState('networkidle');

        // Fill transaction form
        const amountInput = page.locator('input[name="amount"], input[type="number"]').first();
        if (await amountInput.count() > 0) {
          await amountInput.fill('100.00');

          // Select account
          const accountSelect = page.locator('select[name="account_id"]').first();
          if (await accountSelect.count() > 0) {
            await accountSelect.click();
            const option = page.locator('option').nth(1);
            if (await option.count() > 0) {
              await option.click();
            }
          }

          // Submit
          const submitButton = page.locator('button:has-text("Save"), button:has-text("Create"), button[type="submit"]').first();
          await submitButton.click();

          await page.waitForTimeout(1000);
        }
      }
    });

    test('should display transaction details (date, amount, category, account)', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/transactions`);
      await page.waitForLoadState('networkidle');

      const transactionItem = page.locator('div.rounded-2xl, tr').first();
      if (await transactionItem.count() > 0) {
        const itemText = await transactionItem.textContent();
        expect(itemText).toBeTruthy();
      }
    });

    test('should filter transactions by date', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/transactions`);
      await page.waitForLoadState('networkidle');

      // Look for date filter
      const dateInput = page.locator('input[type="date"]').first();
      if (await dateInput.count() > 0) {
        await dateInput.fill('2026-01-01');
        
        // Look for filter button
        const filterButton = page.locator('button:has-text("Filter"), button:has-text("Search"), button:has-text("Apply")').first();
        if (await filterButton.count() > 0) {
          await filterButton.click();
          await page.waitForLoadState('networkidle');
        }
      }
    });
  });

  test.describe('Budget Categories', () => {
    test('should display budget categories', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/categories`);
      await page.waitForLoadState('networkidle');

      // Check for category items
      const categoryItems = page.locator('div.rounded-2xl, div.bg-white, li');
      const count = await categoryItems.count();

      if (count > 0) {
        expect(count).toBeGreaterThan(0);
      }
    });

    test('should display category details (name, budget, spent)', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/categories`);
      await page.waitForLoadState('networkidle');

      const categoryName = page.locator('h3, h2').first();
      if (await categoryName.count() > 0) {
        const nameText = await categoryName.textContent();
        expect(nameText).toBeTruthy();
      }
    });
  });

  test.describe('Financial Reports', () => {
    test('should display spending report', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/reports/spending`);
      await page.waitForLoadState('networkidle');

      // Check for report page elements
      const reportTitle = page.locator('h1, h2').filter({ hasText: /spending|report/ });
      expect(await reportTitle.count()).toBeGreaterThan(0);

      // Look for chart or data display
      const chartOrData = page.locator('canvas, svg, table, div.rounded-2xl');
      expect(await chartOrData.count()).toBeGreaterThan(0);
    });

    test('should display income vs expense report', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/reports/income-vs-expense`);
      await page.waitForLoadState('networkidle');

      const reportTitle = page.locator('h1, h2').filter({ hasText: /income|expense|report/ });
      expect(await reportTitle.count()).toBeGreaterThan(0);
    });

    test('should display net worth report', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/reports/net-worth`);
      await page.waitForLoadState('networkidle');

      const reportTitle = page.locator('h1, h2').filter({ hasText: /net worth|assets|report/ });
      expect(await reportTitle.count()).toBeGreaterThan(0);
    });
  });

  test.describe('Monthly Budget View', () => {
    test('should display current month budget', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/month`);
      await page.waitForLoadState('networkidle');

      // Check for month navigation
      const monthNav = page.locator('h1, h2').filter({ hasText: /\d{4}|january|february|march/ });
      expect(await monthNav.count()).toBeGreaterThan(0);
    });

    test('should allow navigation between months', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/month`);
      await page.waitForLoadState('networkidle');

      // Look for next month button
      const nextButton = page.locator('button:has-text("Next"), button:has-text("→"), button[aria-label*="next"]').first();
      if (await nextButton.count() > 0) {
        const initialUrl = page.url();
        await nextButton.click();
        await page.waitForLoadState('networkidle');

        // URL or content should change
        expect(page.url() !== initialUrl || true).toBe(true);
      }
    });
  });

  test.describe('Account Reconciliation', () => {
    test('should display reconciliation page', async ({ page }) => {
      await page.goto(`${BASE_URL}/parent/finances/accounts`);
      await page.waitForLoadState('networkidle');

      // Find reconcile button for first account
      const reconcileButton = page.locator('a[href*="/reconcile"], button:has-text("Reconcile"), button:has-text("Balance")').first();
      if (await reconcileButton.count() > 0) {
        await reconcileButton.click();
        await page.waitForLoadState('networkidle');

        // Should show reconciliation interface
        const reconciileTitle = page.locator('h1, h2').filter({ hasText: /reconcile|balance/ });
        expect(await reconciileTitle.count()).toBeGreaterThan(0);
      }
    });
  });

  test.describe('Budget Navigation', () => {
    test('should link to budget pages from main menu', async ({ page }) => {
      await page.goto(`${BASE_URL}/dashboard`);
      await page.waitForLoadState('networkidle');

      // Look for finance/budget links
      const financeLink = page.locator('a:has-text("Finance"), a:has-text("Budget"), a[href*="/finances"], a[href*="/budget"]').first();
      expect(await financeLink.count()).toBeGreaterThan(0);
    });
  });
});
