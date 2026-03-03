# Family Task Manager - End-to-End Tests

Comprehensive Playwright e2e test suite for the Family Task Manager application.

## Test Coverage

The test suite includes **71 tests** covering all major features:

### 1. Authentication (5 tests)
- Login with valid credentials
- Error handling for invalid credentials
- Email and password field validation
- Registration flow with password matching
- Logout and session management

### 2. Task Management (7 tests)
- Task creation with validation
- Task editing
- Task deletion
- Task listing and display
- Task assignment to family members
- Task filtering by status

### 3. Reward Management (13 tests)
- Reward creation with categories (treats, privileges, activities, money, toys, screen_time)
- Reward editing and category updates
- Reward deletion
- Reward listing and filtering
- Category validation
- Child reward redemption
- Default points value validation

### 4. Member Management (13 tests)
- Display family member list
- Member details (name, role, points)
- Member role distinction (parent, teen, child)
- Member invitation system
- Family invitation code display and copying
- Member points display and adjustment
- Member status (active/inactive)
- Member deactivation (with last parent protection)
- Member profile view

### 5. Assignment Management (9 tests)
- Task assignment creation
- Assignment listing and display
- Status updates (mark complete, approve)
- Assignment deletion
- Assignment filtering by status
- Assignment due date display
- Child view of pending assignments

### 6. Budget & Finance Management (21 tests)
- Budget dashboard overview
- Account management (list, create, display)
- Transaction management (list, create, filter)
- Budget categories display
- Financial reports (spending, income vs expense, net worth)
- Monthly budget view and navigation
- Account reconciliation
- Budget navigation from main menu

### 7. Login (3 tests - legacy)
- Login flow with detailed logging

## Running Tests

### Install Dependencies
```bash
cd e2e-tests
npm install
```

### Run All Tests
```bash
npm test
```

### Run Specific Test Suite
```bash
npm run test:auth       # Run authentication tests
npm run test:tasks      # Run task management tests
npm run test:rewards    # Run reward management tests
npm run test:assignments # Run assignment tests
npm run test:members    # Run member management tests
npm run test:budget     # Run budget/finance tests
```

### Run with UI
```bash
npm run test:ui
```
Opens Playwright Test UI where you can run individual tests and debug.

### Run in Debug Mode
```bash
npm run test:debug
```
Opens Playwright Inspector for debugging.

### Run in Headed Mode
```bash
npm run test:headed
```
Runs tests with visible browser window.

## Test Files

- **auth.spec.js** - Authentication flows (login, register, logout, session)
- **tasks.spec.js** - Task CRUD operations and management
- **rewards.spec.js** - Reward management and redemption
- **assignments.spec.js** - Task assignments and status tracking
- **members.spec.js** - Family member management
- **budget.spec.js** - Budget, accounts, transactions, and financial reports

## Configuration

### playwright.config.js

Key settings:
- **Base URL**: `http://localhost:3003`
- **Timeout**: 30 seconds per test
- **Expect Timeout**: 5 seconds for assertions
- **Workers**: 1 (sequential execution for stability)
- **Retries**: 1 automatic retry on failure
- **Screenshots**: Only on failure
- **Videos**: Retained on failure
- **Reporter**: HTML report + JUnit XML (for CI/CD)

## Demo User Credentials

Tests use these demo users (from seed_data.py):

```
Parent:
- Email: mom@demo.com
- Password: password123
- Email: dad@demo.com
- Password: password123

Child:
- Email: emma@demo.com
- Password: password123

Teen:
- Email: lucas@demo.com
- Password: password123
```

## Test Environment Requirements

- Local development server running on `http://localhost:3003`
- Backend API on `http://localhost:8002`
- Demo database with seeded data
- All Docker services running (`docker compose up`)

## Best Practices

1. **Robust Selectors**: Tests use flexible selectors that match multiple possible HTML structures
2. **Waits**: Proper use of `waitForLoadState('networkidle')` and `waitForTimeout()`
3. **Assertions**: Clear and specific assertions for each test
4. **Error Handling**: Graceful handling of missing elements with fallbacks
5. **Data Isolation**: Each test is independent and doesn't rely on test order
6. **User Roles**: Tests exercise different user roles (parent, child, teen)

## Common Issues

### Tests Timeout
- Ensure backend and frontend are running
- Check network connectivity
- Increase timeout in playwright.config.js

### Element Not Found
- Tests use flexible selectors to handle UI changes
- Check console logs in test reports
- Use `--headed` flag to see what's happening

### Flaky Tests
- Sequential execution (workers: 1) helps reduce flakiness
- Retries help with transient failures
- Wait for proper load states instead of fixed delays

## CI/CD Integration

Tests generate:
- **HTML Report**: `playwright-report/index.html`
- **JUnit XML**: `test-results/results.xml`
- **Screenshots**: `test-results/` folder on failures
- **Videos**: `test-results/` folder on failures

These can be integrated into GitHub Actions or other CI/CD pipelines.

## Example Test Output

```
Running 71 tests using 1 worker

  ✓ Authentication › Login Flow › should login with valid credentials
  ✓ Task Management › Task Creation › should create a new task
  ✓ Reward Management › should create reward with treats category
  ✓ Member Management › should display family member list
  ✓ Assignment Management › should create a new task assignment
  ✓ Budget & Finance › Accounts Management › should display list of accounts
  
  ... (65 more tests)

71 passed (2m 15s)
```

## Maintenance

### Adding New Tests

1. Create test in appropriate `.spec.js` file
2. Follow naming convention: `should [action] [expectation]`
3. Use existing test patterns and selectors
4. Add to appropriate describe block
5. Test locally before committing

### Updating Selectors

If UI changes, update selectors in relevant test file:
```javascript
const input = page.locator('input[name="field"]'); // Change selector
```

### Debugging Failing Tests

```bash
# Run single test with debug
npx playwright test auth.spec.js:16 --debug

# Run with headed browser
npm run test:headed

# Check test report
npx playwright show-report
```

## Development Workflow

1. Start dev environment: `docker compose up`
2. Make UI changes
3. Run affected tests: `npm run test:[feature]`
4. Fix failing tests
5. Run full suite: `npm test`
6. Commit both code and test changes

## Notes

- Tests are written in CommonJS (not ES modules) for compatibility
- Base URL is configurable in playwright.config.js
- Tests run sequentially (single worker) for stability with shared demo data
- Mock data is NOT used; tests interact with real API and database
- All tests clean up after themselves (use unique identifiers for data)
