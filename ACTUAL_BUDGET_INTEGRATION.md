# Actual Budget Integration Plan for Family Task Manager

**Date**: February 28, 2026  
**Status**: Planning Phase  
**Reason**: Actual Budget GUI is no longer accessible; need to integrate all functionality into Family Task Manager  

---

## Executive Summary

Since Actual Budget's GUI is no longer accessible, we need to replicate ALL core budgeting features within the Family Task Manager application. This document inventories all Actual Budget features and provides an implementation roadmap.

---

## Core Actual Budget Features to Integrate

### 1. **Budget Management (Envelope Budgeting)**

#### Features
- **Monthly Budget Creation**: Assign money to categories each month
- **Category Groups**: Organize categories into groups (e.g., "Mandado", "Servicios", "Entretenimiento")
- **Individual Categories**: Line items within groups
- **Budgeted Amount**: How much money is allocated to each category
- **Available Amount**: Current balance in each category
- **Activity**: Spending/income in the category for the month
- **Rollover**: Leftover money carries to next month
- **Overspending Handling**: Automatic or manual coverage options
- **Hold for Next Month**: Reserve income for future budgeting

#### Implementation Priority
🔴 **CRITICAL** - Core budgeting functionality

#### Database Schema Needed
```sql
-- Category Groups
CREATE TABLE budget_category_groups (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    name VARCHAR(100) NOT NULL,
    sort_order INT,
    is_income BOOLEAN DEFAULT FALSE,
    hidden BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Categories
CREATE TABLE budget_categories (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    group_id UUID NOT NULL REFERENCES budget_category_groups(id),
    name VARCHAR(100) NOT NULL,
    sort_order INT,
    hidden BOOLEAN DEFAULT FALSE,
    rollover_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Monthly Budget Allocations
CREATE TABLE budget_allocations (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    category_id UUID NOT NULL REFERENCES budget_categories(id),
    month DATE NOT NULL, -- First day of month
    budgeted_amount INT NOT NULL, -- Cents
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(category_id, month)
);
```

#### API Endpoints Needed
- `GET /api/budget/month/:year-:month` - Get budget for a month
- `POST /api/budget/allocations` - Update category allocation
- `GET /api/budget/category-groups` - List all category groups
- `POST /api/budget/category-groups` - Create category group
- `PUT /api/budget/category-groups/:id` - Update category group
- `DELETE /api/budget/category-groups/:id` - Delete category group
- `GET /api/budget/categories` - List all categories
- `POST /api/budget/categories` - Create category
- `PUT /api/budget/categories/:id` - Update category
- `DELETE /api/budget/categories/:id` - Delete category
- `POST /api/budget/transfer` - Transfer money between categories
- `POST /api/budget/hold-funds` - Hold funds for next month

#### Astro Pages/Components Needed
- `/budget/month/[year]/[month]` - Main budget view (like Actual's budget screen)
- `BudgetMonthView.astro` - Monthly budget table component
- `CategoryGroup.astro` - Category group with categories
- `CategoryRow.astro` - Individual category row with allocation controls
- `BudgetHeader.astro` - Month selector, "To Budget" amount display
- `CategoryModal.astro` - Create/edit categories
- `TransferModal.astro` - Transfer money between categories

---

### 2. **Account Management**

#### Features
- **Account Types**: 
  - Checking
  - Savings
  - Credit Card
  - Investment
  - Mortgage/Loan
  - Other Assets/Liabilities
- **Account Balance Tracking**: Real-time balance calculation
- **Account Reconciliation**: Mark transactions as cleared/reconciled
- **Closed Accounts**: Archive old accounts
- **Account Notes**: Descriptions and metadata

#### Implementation Priority
🔴 **CRITICAL** - Required for transactions

#### Database Schema Needed
```sql
-- Accounts
CREATE TABLE budget_accounts (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    name VARCHAR(200) NOT NULL,
    type VARCHAR(50) NOT NULL, -- 'checking', 'savings', 'credit', 'investment', 'loan', 'other'
    offbudget BOOLEAN DEFAULT FALSE, -- Tracking vs Budget accounts
    closed BOOLEAN DEFAULT FALSE,
    notes TEXT,
    sort_order INT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### API Endpoints Needed
- `GET /api/budget/accounts` - List all accounts
- `POST /api/budget/accounts` - Create account
- `PUT /api/budget/accounts/:id` - Update account
- `DELETE /api/budget/accounts/:id` - Delete/close account
- `GET /api/budget/accounts/:id/balance` - Get current balance
- `POST /api/budget/accounts/:id/reconcile` - Mark reconciled

#### Astro Pages/Components Needed
- `/budget/accounts` - Accounts list page
- `/budget/accounts/[id]` - Individual account register
- `AccountList.astro` - List of all accounts
- `AccountCard.astro` - Account summary card
- `AccountModal.astro` - Create/edit account
- `ReconcileModal.astro` - Reconciliation interface

---

### 3. **Transaction Management**

#### Features
- **Transaction Entry**: Manual transaction creation
- **Transaction Categories**: Assign to budget categories
- **Payees**: Track who money went to/came from
- **Transfer Transactions**: Move money between accounts
- **Split Transactions**: Divide one transaction into multiple categories
- **Transaction Notes**: Descriptions and memos
- **Transaction Dates**: Post date and cleared date
- **Import Transactions**: OFX, QFX, CSV import
- **Cleared/Pending Status**: Track transaction status
- **Search & Filter**: Find transactions by various criteria
- **Bulk Operations**: Select multiple, categorize, delete

#### Implementation Priority
🔴 **CRITICAL** - Core functionality

#### Database Schema Needed
```sql
-- Payees
CREATE TABLE budget_payees (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    name VARCHAR(200) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Transactions
CREATE TABLE budget_transactions (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    account_id UUID NOT NULL REFERENCES budget_accounts(id),
    date DATE NOT NULL,
    amount INT NOT NULL, -- Cents (negative = expense, positive = income)
    payee_id UUID REFERENCES budget_payees(id),
    category_id UUID REFERENCES budget_categories(id),
    notes TEXT,
    cleared BOOLEAN DEFAULT FALSE,
    reconciled BOOLEAN DEFAULT FALSE,
    imported_id VARCHAR(255), -- For deduplication
    parent_id UUID REFERENCES budget_transactions(id), -- For splits
    is_parent BOOLEAN DEFAULT FALSE, -- Is this a split parent?
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Transaction Splits
CREATE TABLE budget_transaction_splits (
    id UUID PRIMARY KEY,
    parent_transaction_id UUID NOT NULL REFERENCES budget_transactions(id),
    category_id UUID NOT NULL REFERENCES budget_categories(id),
    amount INT NOT NULL, -- Cents
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### API Endpoints Needed
- `GET /api/budget/transactions` - List transactions (filterable)
- `POST /api/budget/transactions` - Create transaction
- `PUT /api/budget/transactions/:id` - Update transaction
- `DELETE /api/budget/transactions/:id` - Delete transaction
- `POST /api/budget/transactions/bulk` - Bulk operations
- `POST /api/budget/transactions/import` - Import from file
- `GET /api/budget/payees` - List payees
- `POST /api/budget/payees` - Create payee
- `PUT /api/budget/payees/:id` - Update payee
- `DELETE /api/budget/payees/:id` - Delete/merge payee

#### Astro Pages/Components Needed
- `/budget/accounts/[id]/transactions` - Account register (transaction list)
- `/budget/transactions/all` - All transactions view
- `TransactionList.astro` - Transactions table
- `TransactionRow.astro` - Individual transaction row
- `TransactionForm.astro` - Create/edit transaction modal
- `TransactionSplitEditor.astro` - Split transaction interface
- `TransactionImport.astro` - File upload and import wizard
- `PayeeSelect.astro` - Payee dropdown with autocomplete
- `CategorySelect.astro` - Category picker dropdown

---

### 4. **Scheduled Transactions (Recurring)**

#### Features
- **Recurring Setup**: Define frequency (daily, weekly, monthly, yearly)
- **Auto-Post**: Automatically create transactions on schedule
- **Reminders**: Notify before upcoming bills
- **Bill Tracking**: Mark bills as paid
- **Templates**: Save transaction templates
- **Skip/Postpone**: Adjust individual occurrences

#### Implementation Priority
🟡 **HIGH** - Important for household budgeting

#### Database Schema Needed
```sql
-- Schedules
CREATE TABLE budget_schedules (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    name VARCHAR(200) NOT NULL,
    account_id UUID NOT NULL REFERENCES budget_accounts(id),
    payee_id UUID REFERENCES budget_payees(id),
    category_id UUID REFERENCES budget_categories(id),
    amount INT NOT NULL, -- Cents
    notes TEXT,
    frequency VARCHAR(50) NOT NULL, -- 'daily', 'weekly', 'monthly', 'yearly'
    frequency_value INT DEFAULT 1, -- Every N days/weeks/months
    start_date DATE NOT NULL,
    end_date DATE, -- NULL = forever
    next_due_date DATE NOT NULL,
    auto_post BOOLEAN DEFAULT FALSE,
    completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Schedule Occurrences (tracking)
CREATE TABLE budget_schedule_occurrences (
    id UUID PRIMARY KEY,
    schedule_id UUID NOT NULL REFERENCES budget_schedules(id),
    due_date DATE NOT NULL,
    transaction_id UUID REFERENCES budget_transactions(id), -- NULL if not posted yet
    skipped BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### API Endpoints Needed
- `GET /api/budget/schedules` - List schedules
- `POST /api/budget/schedules` - Create schedule
- `PUT /api/budget/schedules/:id` - Update schedule
- `DELETE /api/budget/schedules/:id` - Delete schedule
- `POST /api/budget/schedules/:id/post` - Manually post occurrence
- `POST /api/budget/schedules/:id/skip` - Skip occurrence
- `GET /api/budget/schedules/upcoming` - Upcoming bills/income

#### Astro Pages/Components Needed
- `/budget/schedules` - Schedules list page
- `SchedulesList.astro` - All schedules table
- `ScheduleForm.astro` - Create/edit schedule modal
- `UpcomingBills.astro` - Dashboard widget for upcoming bills
- `ScheduleCalendar.astro` - Calendar view of scheduled transactions

---

### 5. **Reports & Analytics**

#### Features
- **Net Worth**: Assets vs Liabilities over time
- **Spending Report**: Category breakdown
- **Income vs Expense**: Monthly comparison
- **Cash Flow**: Money in/out over time
- **Custom Date Ranges**: Filter by any date range
- **Category Trends**: Spending patterns by category
- **Account Balances**: Balance history chart
- **Budget vs Actual**: Planned vs actual spending

#### Implementation Priority
🟢 **MEDIUM** - Nice to have, not critical for MVP

#### Database Schema Needed
```sql
-- Report snapshots (for performance)
CREATE TABLE budget_monthly_snapshots (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    month DATE NOT NULL,
    total_income INT NOT NULL,
    total_expenses INT NOT NULL,
    net_worth INT NOT NULL,
    category_data JSONB, -- Category-level aggregates
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(family_id, month)
);
```

#### API Endpoints Needed
- `GET /api/budget/reports/net-worth` - Net worth over time
- `GET /api/budget/reports/spending` - Spending breakdown
- `GET /api/budget/reports/income-expense` - Income vs expense
- `GET /api/budget/reports/cashflow` - Cash flow
- `GET /api/budget/reports/budget-vs-actual` - Budget performance

#### Astro Pages/Components Needed
- `/budget/reports` - Reports dashboard
- `/budget/reports/net-worth` - Net worth chart
- `/budget/reports/spending` - Spending breakdown
- `ReportsDashboard.astro` - Main reports page
- `NetWorthChart.astro` - Net worth line chart
- `SpendingDonut.astro` - Category spending pie/donut chart
- `CashFlowChart.astro` - Income/expense bar chart
- `BudgetPerformance.astro` - Budget vs actual table

---

### 6. **Rules & Automation**

#### Features
- **Transaction Rules**: Auto-categorize based on patterns
- **Payee Mapping**: Link imported payees to existing payees
- **Conditional Rules**: If/then logic (e.g., "if payee contains 'Amazon', categorize as Shopping")
- **Rule Priority**: Order of rule execution
- **Bulk Apply**: Apply rules to existing transactions

#### Implementation Priority
🟢 **MEDIUM** - Quality of life improvement

#### Database Schema Needed
```sql
-- Transaction Rules
CREATE TABLE budget_rules (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    name VARCHAR(200) NOT NULL,
    conditions JSONB NOT NULL, -- {field: 'payee', operator: 'contains', value: 'Amazon'}
    actions JSONB NOT NULL, -- {field: 'category_id', value: 'uuid...'}
    priority INT DEFAULT 0,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### API Endpoints Needed
- `GET /api/budget/rules` - List rules
- `POST /api/budget/rules` - Create rule
- `PUT /api/budget/rules/:id` - Update rule
- `DELETE /api/budget/rules/:id` - Delete rule
- `POST /api/budget/rules/apply` - Apply rules to existing transactions

#### Astro Pages/Components Needed
- `/budget/settings/rules` - Rules management page
- `RulesList.astro` - All rules table
- `RuleForm.astro` - Create/edit rule modal
- `RuleConditionBuilder.astro` - Visual rule builder

---

### 7. **Multi-Currency Support**

#### Features
- **Primary Currency**: Family's default currency
- **Foreign Accounts**: Accounts in different currencies
- **Exchange Rates**: Manual or automatic rate updates
- **Conversion Display**: Show amounts in primary currency

#### Implementation Priority
⚪ **LOW** - Not needed for Martinez family (MXN only)

#### Database Schema Needed
```sql
-- Exchange rates (if needed)
CREATE TABLE budget_exchange_rates (
    id UUID PRIMARY KEY,
    from_currency VARCHAR(3) NOT NULL,
    to_currency VARCHAR(3) NOT NULL,
    rate DECIMAL(20, 10) NOT NULL,
    effective_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Add to budget_accounts:
ALTER TABLE budget_accounts ADD COLUMN currency VARCHAR(3) DEFAULT 'MXN';
```

---

### 8. **Backup & Sync**

#### Features
- **Automatic Backups**: Regular snapshots
- **Export Data**: Download as CSV/JSON
- **Import Data**: Restore from backup
- **Sync Across Devices**: (Already implemented via Actual Budget server)

#### Implementation Priority
🟡 **HIGH** - Data safety is critical

#### Database Schema Needed
```sql
-- Backups metadata
CREATE TABLE budget_backups (
    id UUID PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id),
    backup_date TIMESTAMP NOT NULL,
    file_path VARCHAR(500),
    file_size_bytes BIGINT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### API Endpoints Needed
- `POST /api/budget/backup` - Create backup
- `GET /api/budget/backups` - List backups
- `POST /api/budget/restore/:id` - Restore from backup
- `GET /api/budget/export` - Export data (CSV/JSON)

---

### 9. **Settings & Preferences**

#### Features
- **Family Settings**: Budget name, currency, date format
- **User Preferences**: Dark mode, number format, language
- **Notification Settings**: Email/push notifications for bills
- **Privacy Settings**: Who can view budget

#### Implementation Priority
🟢 **MEDIUM** - Can use existing user settings system

#### Database Schema Needed
```sql
-- Add to families table:
ALTER TABLE families ADD COLUMN budget_settings JSONB DEFAULT '{
    "currency": "MXN",
    "date_format": "YYYY-MM-DD",
    "number_format": "1,234.56",
    "first_month": "2026-03-01"
}'::jsonb;

-- Add to users table:
ALTER TABLE users ADD COLUMN budget_preferences JSONB DEFAULT '{
    "theme": "light",
    "notifications_enabled": true,
    "default_account_id": null
}'::jsonb;
```

---

## Implementation Roadmap

### Phase 1: Core Budget Foundation (Weeks 1-3)
**Goal**: Basic budgeting and transaction tracking

- [ ] Database schema for categories, accounts, transactions
- [ ] Backend API for budget CRUD operations
- [ ] Astro pages for budget month view
- [ ] Category and account management UI
- [ ] Basic transaction entry
- [ ] Budget allocation interface

**Deliverable**: Parents can create categories, accounts, and budget for a month

---

### Phase 2: Transaction Management (Weeks 4-6)
**Goal**: Full transaction tracking

- [ ] Payee management system
- [ ] Transaction import (CSV)
- [ ] Split transactions
- [ ] Transaction search & filtering
- [ ] Account reconciliation
- [ ] Transfer transactions

**Deliverable**: Parents can import transactions, categorize, and track spending

---

### Phase 3: Schedules & Automation (Weeks 7-8)
**Goal**: Recurring transactions and automation

- [ ] Scheduled transactions system
- [ ] Auto-posting recurring bills
- [ ] Transaction rules engine
- [ ] Bulk transaction operations
- [ ] Upcoming bills dashboard

**Deliverable**: Parents can set up recurring bills and auto-categorization

---

### Phase 4: Reports & Analytics (Weeks 9-10)
**Goal**: Financial insights

- [ ] Net worth tracking
- [ ] Spending reports by category
- [ ] Income vs expense charts
- [ ] Budget performance dashboard
- [ ] Monthly snapshots for performance

**Deliverable**: Parents can view spending patterns and trends

---

### Phase 5: Points Integration (Weeks 11-12)
**Goal**: Connect points system to budget

- [ ] Automatic child account creation
- [ ] Points-to-money conversion deposit flow
- [ ] Child account balance display
- [ ] Domingo category auto-creation
- [ ] Sync service integration with new schema

**Deliverable**: Points conversion deposits into proper budget structure

---

### Phase 6: Polish & Optimization (Weeks 13-14)
**Goal**: Production-ready features

- [ ] Backup system
- [ ] Data export/import
- [ ] Mobile-responsive design
- [ ] Performance optimization
- [ ] User documentation

**Deliverable**: Production-ready budget system

---

## Technical Architecture

### Backend Stack
- **FastAPI** (existing backend)
- **PostgreSQL** (existing database)
- **SQLAlchemy** async ORM
- **Pydantic** models for validation

### Frontend Stack
- **Astro 5 SSR** (existing frontend)
- **Tailwind CSS v4** (existing styling)
- **Chart.js** or **Recharts** for visualizations
- **Alpine.js** for interactive components (already used)

### Data Flow
```
User → Astro Page → API Endpoint → Service Layer → Repository → Database
                                         ↓
                                    Actual Budget
                                    (sync only, not primary)
```

### Actual Budget Role
- **Old**: Primary budget system, GUI for management
- **New**: Sync target only for mobile app access (if needed)
- Budget data now lives in PostgreSQL
- Finance API becomes read-only view for mobile

---

## Migration Strategy

### Option A: Parallel Systems (Recommended)
1. Build new budget system in Family Task Manager
2. Keep Actual Budget sync service running
3. **Two-way sync**: FTM ↔ Actual Budget
4. Eventually deprecate Actual Budget sync

### Option B: Import and Replace
1. Export all data from Actual Budget
2. Import into Family Task Manager database
3. Disable Actual Budget entirely
4. Use FTM as single source of truth

### Recommendation
**Option A** - Keep Actual Budget as backup and mobile sync target during transition period

---

## Key Differences from Actual Budget

### What We Keep
- Envelope budgeting model
- Category groups and categories
- Transaction tracking
- Account management
- Scheduled transactions
- Reports

### What We Customize
- **Family-centric**: All data scoped to family
- **Role-based**: Parents manage budget, children view their allowances
- **Points integration**: Seamless point-to-money conversion
- **Simplified UI**: Focus on family budget use case, not power users
- **Mobile-first**: Responsive design from day one

### What We Skip (for MVP)
- Multi-currency (can add later)
- Investment tracking (not needed for family budgeting)
- Advanced rules (simple ones first)
- Bank sync (manual import sufficient)

---

## Security Considerations

### Data Access Control
- **Parents**: Full budget access
- **Teens**: View their own accounts only
- **Children**: View their own accounts only
- Multi-tenant isolation (existing family_id pattern)

### API Security
- JWT authentication (existing)
- Family-scoped queries (existing pattern)
- CORS protection (existing)
- SQL injection prevention (SQLAlchemy parameterization)

---

## Next Steps

1. **Fix PointsConverter.astro syntax error** (BLOCKER)
2. **Get stakeholder approval** on this plan
3. **Create detailed DB migration** for Phase 1 schema
4. **Set up Astro pages** structure for budget views
5. **Build Phase 1 backend API** endpoints
6. **Implement Phase 1 frontend** components
7. **Test with Martinez family** before proceeding to Phase 2

---

## Questions for Stakeholder

1. **Timeline**: Is 14 weeks (3.5 months) acceptable?
2. **MVP Scope**: Should we start with Phase 1-2 only and iterate?
3. **Actual Budget**: Keep as sync target or deprecate entirely?
4. **Reporting**: How detailed should reports be? (affects Phase 4 scope)
5. **Mobile**: Desktop-first or mobile-first design priority?

---

## Resources

- [Actual Budget Documentation](https://actualbudget.org/docs/)
- [Actual Budget API Reference](https://actualbudget.org/docs/api/reference)
- [Astro 5 Docs](https://docs.astro.build/)
- [Envelope Budgeting Guide](https://actualbudget.org/docs/getting-started/envelope-budgeting)

---

**Document Version**: 1.0  
**Last Updated**: February 28, 2026  
**Author**: OpenCode AI Assistant  
**Stakeholder**: Juan Carlos Martinez (jcatsapsre@gmail.com)
