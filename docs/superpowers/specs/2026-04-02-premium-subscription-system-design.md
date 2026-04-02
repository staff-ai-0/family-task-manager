# Premium Subscription System — Design Spec

**Date:** 2026-04-02
**Status:** Approved
**Scope:** Database models, gating middleware, PayPal billing, usage tracking

---

## Overview

Add a tiered subscription system to Family Task Manager. Three plans (Free, Plus, Pro) gate access to premium features like AI receipt scanning, advanced budget tools, and higher limits. PayPal handles billing with monthly and annual cycles.

## Subscription Tiers

| Feature | Free | Plus ($5/mo, $50/yr) | Pro ($15/mo, $150/yr) |
|---------|------|----------------------|-----------------------|
| Tasks & rewards | Full | Full | Full |
| Family members | 4 | 8 | Unlimited |
| Budget accounts | 2 | 5 | Unlimited |
| Budget transactions/month | 30 | 200 | Unlimited |
| Budget reports & goals | No | Yes | Yes |
| Recurring transactions | No | 5 | Unlimited |
| CSV import | No | Yes | Yes |
| AI receipt scanning | No | 15/month | Unlimited |
| Future AI features | No | Limited | Full |

Annual pricing gives 2 months free (e.g., Plus: $50/yr instead of $60).

## Data Model

### Table: `subscription_plans`

Stores the plan definitions. Seeded at deployment, rarely changed.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| name | VARCHAR(50) | `"free"`, `"plus"`, `"pro"` — unique |
| display_name | VARCHAR(100) | `"Free"`, `"Plus"`, `"Pro"` |
| display_name_es | VARCHAR(100) | `"Gratis"`, `"Plus"`, `"Pro"` |
| price_monthly_cents | INTEGER | Amount in cents (0 for free) |
| price_annual_cents | INTEGER | Amount in cents (0 for free) |
| paypal_plan_id_monthly | VARCHAR(100) | PayPal billing plan ID for monthly |
| paypal_plan_id_annual | VARCHAR(100) | PayPal billing plan ID for annual |
| limits | JSONB | Feature limits (see below) |
| is_active | BOOLEAN | Soft-disable a plan |
| sort_order | INTEGER | Display order |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### Limits JSONB Structure

```json
{
  "max_family_members": 8,
  "max_budget_accounts": 5,
  "max_budget_transactions_per_month": 200,
  "max_recurring_transactions": 5,
  "budget_reports": true,
  "budget_goals": true,
  "csv_import": true,
  "max_receipt_scans_per_month": 15,
  "ai_features": true
}
```

For "unlimited" values, use `-1`. For boolean features, `true`/`false`. Free plan example:

```json
{
  "max_family_members": 4,
  "max_budget_accounts": 2,
  "max_budget_transactions_per_month": 30,
  "max_recurring_transactions": 0,
  "budget_reports": false,
  "budget_goals": false,
  "csv_import": false,
  "max_receipt_scans_per_month": 0,
  "ai_features": false
}
```

### Table: `family_subscriptions`

One active subscription per family. Families without a row default to Free.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| family_id | UUID FK → families | Unique (one active sub per family) |
| plan_id | UUID FK → subscription_plans | |
| billing_cycle | VARCHAR(20) | `"monthly"` or `"annual"` |
| status | VARCHAR(20) | `"active"`, `"past_due"`, `"cancelled"`, `"expired"` |
| paypal_subscription_id | VARCHAR(100) | PayPal subscription ID |
| current_period_start | TIMESTAMP | |
| current_period_end | TIMESTAMP | |
| cancelled_at | TIMESTAMP | Nullable — when user cancelled |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### Table: `usage_tracking`

Tracks per-feature usage counts per month per family.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| family_id | UUID FK → families | |
| feature | VARCHAR(50) | `"receipt_scan"`, `"budget_transaction"`, `"csv_import"` |
| period_start | DATE | First day of the month |
| count | INTEGER | Current usage count |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |
| | UNIQUE | (family_id, feature, period_start) |

## Gating Middleware

### FastAPI Dependencies

**`get_family_plan()`** — returns the family's current plan and limits:

```python
async def get_family_plan(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FamilyPlan:
    # Returns: plan name, limits dict, subscription status
    # Defaults to "free" plan limits if no subscription exists
```

**`require_feature(feature_name)`** — factory that returns a dependency checking access:

```python
def require_feature(feature: str):
    async def checker(
        plan: FamilyPlan = Depends(get_family_plan),
        db: AsyncSession = Depends(get_db),
    ):
        # 1. Check if feature is enabled in plan.limits
        # 2. If feature has a numeric limit, check usage_tracking
        # 3. Raise 403 with upgrade info if denied
    return checker
```

**403 Response Schema:**

```json
{
  "error": "upgrade_required",
  "feature": "receipt_scan",
  "plan_needed": "plus",
  "current_usage": 15,
  "limit": 15,
  "message": "Has alcanzado el límite de escaneos este mes. Actualiza a Plus para continuar."
}
```

**Note on `require_feature` vs numeric limits:** `require_feature` handles both boolean and numeric limits. For boolean features (e.g., `csv_import`), it checks the plan's limits for `true`/`false`. For numeric features (e.g., `max_receipt_scans_per_month`), it also queries `usage_tracking` and compares against the limit (`-1` = unlimited, `0` = disabled). Usage is incremented *after* the operation succeeds (not in the dependency), via an explicit `UsageService.increment()` call in the route handler.

### Usage Tracking Service

```python
class UsageService:
    @classmethod
    async def get_usage(cls, db, family_id, feature, month) -> int
    
    @classmethod
    async def increment(cls, db, family_id, feature) -> int
    
    @classmethod
    async def check_limit(cls, db, family_id, feature, limit) -> bool
```

## API Endpoints

### Subscription Management

All require PARENT role.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/subscriptions/plans` | List available plans |
| GET | `/api/subscriptions/current` | Get family's current subscription |
| POST | `/api/subscriptions/checkout` | Create PayPal subscription, return approval URL |
| POST | `/api/subscriptions/activate` | PayPal callback — activate subscription |
| POST | `/api/subscriptions/cancel` | Cancel subscription (remains active until period end) |
| GET | `/api/subscriptions/usage` | Get current month's usage for all features |

### PayPal Integration

Uses PayPal Subscriptions API (already have PayPal SDK integrated):

1. **Checkout:** Backend creates a PayPal subscription with the plan's `paypal_plan_id`, returns approval URL
2. **Activate:** PayPal redirects back, frontend calls `/activate` with subscription ID
3. **Webhooks:** `BILLING.SUBSCRIPTION.ACTIVATED`, `BILLING.SUBSCRIPTION.CANCELLED`, `PAYMENT.SALE.COMPLETED`, `BILLING.SUBSCRIPTION.SUSPENDED` (past_due)

Webhook endpoint: `POST /api/subscriptions/webhook`

### Applying Gates to Existing Endpoints

Add `require_feature()` or `require_feature()` dependencies to:

- `POST /api/budget/transactions/` — count limit (`budget_transaction`)
- `POST /api/budget/transactions/import/csv` — boolean (`csv_import`)
- `GET /api/budget/reports/*` — boolean (`budget_reports`)
- `POST /api/budget/goals/` — boolean (`budget_goals`)
- `POST /api/budget/recurring/` — count limit (`recurring_transaction`)
- `POST /api/budget/receipts/scan` — count limit (`receipt_scan`) *(Spec 2)*

## Frontend Changes

### Subscription Management Page

New page: `frontend/src/pages/parent/settings/subscription.astro`

- Current plan display with usage meters
- Plan comparison table
- Upgrade/downgrade buttons → PayPal checkout flow
- Cancel subscription option
- Billing history (from PayPal)

### Upgrade Prompt Component

New component: `frontend/src/components/UpgradePrompt.astro`

- Shown when 403 `upgrade_required` is received
- Displays which feature is locked and which plan unlocks it
- "Ver Planes" button → subscription page

### Feature Gating in Frontend

Astro middleware (`middleware.ts`) fetches the family's plan on authenticated requests and passes it to pages via `Astro.locals.plan`. Pages conditionally render UI elements:

- Hide buttons for disabled features (show lock icon + "Plus" badge)
- Show usage counters near limits (e.g., "28/30 transacciones este mes")

## Files to Create/Modify

### New Files

| File | Purpose |
|------|---------|
| `backend/app/models/subscription.py` | SubscriptionPlan, FamilySubscription, UsageTracking models |
| `backend/app/services/subscription_service.py` | Plan management, PayPal integration, usage tracking |
| `backend/app/api/routes/subscriptions.py` | Subscription API endpoints |
| `backend/app/core/premium.py` | `get_family_plan()`, `require_feature()`, `require_feature()` dependencies |
| `backend/alembic/versions/xxx_add_subscription_tables.py` | Migration |
| `frontend/src/pages/parent/settings/subscription.astro` | Subscription management page |
| `frontend/src/components/UpgradePrompt.astro` | Upgrade prompt component |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/main.py` | Register subscription router |
| `backend/app/core/config.py` | Add PayPal subscription plan IDs |
| `backend/app/api/routes/budget/transactions.py` | Add `require_feature("budget_transaction")` |
| `backend/app/api/routes/budget/reports.py` | Add `require_feature("budget_reports")` |
| `backend/app/api/routes/budget/goals.py` | Add `require_feature("budget_goals")` |
| `backend/app/api/routes/budget/recurring.py` | Add `require_feature("recurring_transaction")` |
| `frontend/src/middleware.ts` | Fetch and pass plan to pages |
| `frontend/src/pages/parent/settings/index.astro` | Add subscription link |

## Seed Data

Add to `seed_data.py`:

- 3 subscription plans (Free, Plus, Pro) with limits JSONB
- Demo family gets "Plus" subscription (so all features are testable)
- Sample usage_tracking entries

## Testing

- Unit tests for `UsageService` (increment, check limits, monthly reset)
- Unit tests for `require_feature` dependency (allow, deny, upgrade response)
- Integration tests for subscription CRUD endpoints
- Integration tests for feature gating on budget endpoints
- Test that families default to Free when no subscription exists
