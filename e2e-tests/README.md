# Family Task Manager - End-to-End Tests

Comprehensive Playwright e2e test suite for the Family Task Manager application.

## Test Coverage

The suite covers all major features. Per-section counts below are indicative and
drift; `npx playwright test --list` is the authoritative count (152 at the time
the operator-console / Family Bank / CSV-import specs were added).

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

### 8. Operator console — `admin.spec.js`
- `/admin` and `/api/admin/*` return a bare **404** for anonymous visitors and
  for logged-in non-operators (fail-closed contract — never 403, never a
  `/login` bounce)
- Overview renders the live platform-pulse tiles
- Family directory search by member email, opening the family detail page
- One bounded write action (module registry → "restore default") lands in the
  append-only audit log with its operator, action and reason

### 9. Family Bank — `bank.spec.js`
- Kid `/bank`: total balance and the three jars render and match `/api/bank/me`
- Kid move-money modal opens (read-only, posts nothing)
- Parent `/parent/payouts`: owed-to-kids header totals reconcile
- Parent releases an outstanding chore-paycheck week and the server agrees

### 10. Budget CSV import — `budget-import.spec.js`
- Upload → import → the transactions exist on the account with the right signed
  amounts and `imported_id`
- Re-importing the same file is skipped, not duplicated
- The form refuses to post without an account and a file

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

### Run the smoke subset (fast slice)

The highest-value flows are tagged `@smoke` so a pipeline can run a short slice
instead of the whole suite:

```bash
npm run test:smoke        # == playwright test --grep @smoke
npm run test:no-smoke     # everything else (--grep-invert @smoke)
```

`--grep` also composes with the usual filters, e.g.
`npx playwright test budget --grep @smoke`.

The smoke set is one test per critical path, currently:

| Spec | Test | Why it's in the set |
|---|---|---|
| `auth.spec.js` | login with valid credentials | nothing else runs if login is broken |
| `dashboard.spec.js` | `/dashboard` → `/parent` redirect | the post-login landing contract |
| `dashboard.spec.js` | renders parent hub header | the hub actually rendered, not a 500 |
| `tasks.spec.js` | create a new task | core write path |
| `gigs.spec.js` | child completes with proof → parent approves | the full complete→review→credit round trip |
| `budget.spec.js` | budget overview page | the budget surface renders |
| `budget-import.spec.js` | CSV import lands transactions | a real budget-transaction write, end to end |

**Tagging convention**: use Playwright's tag option, not a title suffix —

```js
test('does the thing', { tag: '@smoke' }, async ({ page }) => { /* ... */ });
```

Keep the set small: it is a "is the app fundamentally alive" check, not a
second full suite. Tests that self-skip when their data isn't seeded (e.g. the
gigs round trip) report as *skipped*, which is deliberate — a skip is visible,
a silently-passing no-op is not.

### Run Specific Test Suite
```bash
npm run test:auth       # Run authentication tests
npm run test:tasks      # Run task management tests
npm run test:rewards    # Run reward management tests
npm run test:assignments # Run assignment tests
npm run test:members    # Run member management tests
npm run test:budget     # Run budget/finance tests (budget.spec.js + budget-import.spec.js)
npm run test:admin      # Run operator-console tests
npm run test:bank       # Run Family Bank tests
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
- **budget-import.spec.js** - CSV statement import into a budget account
- **bank.spec.js** - Family Bank: kid jars + parent chore-paycheck release
- **admin.spec.js** - Operator console (`/admin`): fail-closed 404s, directory,
  audited write action

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

## Test Credentials

Tests use env vars with sensible defaults. Set these in your environment or a `.env` file:

| Variable | Default | Role |
|---|---|---|
| `E2E_EMAIL` | `e2e-fresh@example.com` | Parent (most tests) |
| `E2E_PASSWORD` | `fresh1234` | Parent password |
| `E2E_CHILD_EMAIL` | `emma@demo.com` | Child (redemption / child-view tests) |
| `E2E_CHILD_PASSWORD` | `password123` | Child password |
| `E2E_ADMIN_EMAIL` | *(none)* | Platform operator for `/admin` |
| `E2E_ADMIN_PASSWORD` | *(none)* | Operator password |

The `e2e-fresh@example.com` parent account must exist in the DB before running tests. Demo seed accounts (`emma@demo.com`, `lucas@demo.com`) use `password123` (from `seed_data.py`). Set `E2E_CHILD_*` vars to a child member of the same family as `E2E_EMAIL` to enable the full gig-approval flow; otherwise those tests skip automatically.

`E2E_ADMIN_*` has **no default on purpose**. `require_superadmin`
(`backend/app/core/dependencies.py`) demands *both* `users.is_superadmin` and
membership of the `SUPERADMIN_EMAILS` allowlist, and answers 404 when either is
missing — a guessed default would only produce 404s that look like a broken
console. Provision an operator per `docs/DEPLOYMENT.md` → "Granting super-admin
access" (env allowlist + DB flag), then point these vars at it. Without them,
`admin.spec.js` still runs its fail-closed tests (which need no operator) and
skips the rest with a message saying why.

## Test Environment Requirements

- Local development server running on `http://localhost:3003`
- Backend API on `http://localhost:8003`
- Demo database with seeded data
- All services running (`podman compose up`)

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

1. Start dev environment: `podman compose up`
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
