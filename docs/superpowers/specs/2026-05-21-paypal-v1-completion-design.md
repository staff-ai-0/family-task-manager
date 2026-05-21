# PayPal Subscription Completion — v1 Design

**Date**: 2026-05-21
**Author**: Juan + Claude (Opus 4.7)
**Status**: Approved (pre-implementation)

## Goal

Take the 60%-complete PayPal subscription stack from "Coming soon" placeholder to a working end-to-end flow: checkout → 7-day trial → activation → recurring billing → cancel-at-period-end. Apply feature gating to budget/AI routes so the Free vs Plus vs Pro tiers actually mean something.

## Scope

In scope (v1):
- Sandbox PayPal integration with env-var switch to live
- Subscription Plans created via setup script (Plus monthly/annual, Pro monthly/annual — 4 plans)
- 7-day free trial on first subscription per family
- Checkout flow wired from `subscription.astro` → PayPal hosted page → activate callback
- Webhook handler for 3 events: `ACTIVATED`, `CANCELLED`, `PAYMENT.FAILED`
- Cancel-at-period-end semantics
- Feature gating applied to: receipt scan, budget transactions, family members, budget reports/goals/AI booleans

Out of scope (v2+):
- Invoice / billing history page
- Email receipts via Resend
- Annual-cycle UI toggle (plans exist but UI shows monthly only)
- Coupon / promo code application (separate spec)
- Pro-rated upgrades / downgrades mid-cycle
- Dunning / retry beyond 3-day grace

## Current State (pre-work)

Survey 2026-05-21:
- `backend/app/services/paypal_service.py` — full SDK wrapper; methods for create/execute payment, create subscription, verify webhook signature. **Webhook verification method exists but is unused.**
- `backend/app/models/subscription.py` — three tables (`SubscriptionPlan`, `FamilySubscription`, `UsageTracking`) all present, migration applied (`586649b5ef22_add_subscription_tables.py`).
- `backend/app/api/routes/subscriptions.py` — `GET /plans`, `GET /current`, `GET /usage`, `POST /checkout`, `POST /activate`, `POST /cancel` exist. **Two bugs**: `/checkout` doesn't accept `plan_name`/`billing_cycle`; `/activate` hardcodes `plan_name="plus"` instead of reading from session/request.
- `backend/app/core/premium.py` — `require_feature()` exists but **no routes import it**.
- `frontend/src/pages/parent/settings/subscription.astro` — full UI with plan comparison, usage meters. Upgrade button has `disabled` attribute + "Coming soon — PayPal integration pending" tooltip.
- No `POST /api/subscriptions/webhook` endpoint.

## Changes

### 1. Setup script: `scripts/setup-paypal-plans.py`

Idempotent script that creates the PayPal Product + 4 Plans on first run, prints the plan IDs for `.env`.

Behavior:
- Reads `PAYPAL_MODE`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` from env.
- Queries existing PayPal Products via Catalog API. Skips create if name `Family Task Manager` already exists.
- For each of (Plus monthly $5, Plus annual $50, Pro monthly $15, Pro annual $150): query plans for product; create only if missing.
- Each plan has:
  - 7-day trial cycle (free)
  - Regular cycle: monthly or annual, fixed price USD
  - Auto-renew enabled, payment failure threshold = 3 attempts
- Outputs to stdout:
  ```
  PAYPAL_PLAN_ID_PLUS_MONTHLY=P-XXXX...
  PAYPAL_PLAN_ID_PLUS_ANNUAL=P-XXXX...
  PAYPAL_PLAN_ID_PRO_MONTHLY=P-XXXX...
  PAYPAL_PLAN_ID_PRO_ANNUAL=P-XXXX...
  ```

Runtime: standalone script, not invoked at app boot. Operator runs it once per env (sandbox + later live).

### 2. Fix `POST /api/subscriptions/checkout`

Accept request body:
```json
{
  "plan_name": "plus" | "pro",
  "billing_cycle": "monthly" | "annual"
}
```

Flow:
1. Resolve `paypal_plan_id` from `SubscriptionPlan` table (filter `name=plan_name, cycle=billing_cycle`).
2. Call `paypal_service.create_subscription(plan_id, return_url, cancel_url)` where:
   - `return_url = {PUBLIC_URL}/parent/settings/subscription/activate?subscription_id={subscription_id}` — PayPal substitutes `{subscription_id}` token.
   - `cancel_url = {PUBLIC_URL}/parent/settings/subscription?cancelled=1`
3. Insert/upsert `FamilySubscription(family_id, plan_id, paypal_subscription_id, status="pending", billing_cycle)`.
4. Return `{approve_url, paypal_subscription_id}`.

### 3. Fix `POST /api/subscriptions/activate`

Was: hardcoded `plan_name="plus"` (subscriptions.py:228).
Now:
1. Read `subscription_id` from query string (sent by PayPal `return_url`).
2. Call `paypal_service.get_subscription(subscription_id)` to confirm status is `APPROVAL_PENDING`, `ACTIVE`, or trial.
3. Look up the matching pending `FamilySubscription` row (by `paypal_subscription_id`).
4. Update row: `status=trial` if currently in trial else `active`; set `period_start`, `period_end`, `trial_end_at`.
5. Set `family.plan_id` so feature gating sees the upgrade.
6. Return `{ok:true, subscription, redirect_to:"/parent/settings/subscription"}`.

Idempotent: re-hitting `/activate` for an already-active sub is a no-op success.

### 4. New `POST /api/subscriptions/webhook`

Public endpoint (no auth) — PayPal posts here from their servers.

Flow:
1. Read raw body + all `Paypal-*` headers.
2. Call `paypal_service.verify_webhook_signature(headers, body, webhook_id=PAYPAL_WEBHOOK_ID)`. If invalid → 401.
3. Parse `event_id`. Check Redis key `paypal:event:{event_id}` — if present (set), return 200 (already processed; dedupe).
4. Switch on `event_type`:
   - `BILLING.SUBSCRIPTION.ACTIVATED` → upsert `FamilySubscription` to `status="active"`, set `period_end`.
   - `BILLING.SUBSCRIPTION.CANCELLED` → set `cancel_at_period_end=true`, keep status as-is. Daily sweep job (simple cron via `apscheduler` already-present-or-add, **not** Celery — project has no Celery) downgrades any family whose `cancel_at_period_end=true AND period_end < now()` to Free.
   - `BILLING.SUBSCRIPTION.PAYMENT.FAILED` → set `status="payment_failed"`, `payment_failure_at=now()`. Send email via Resend. 3-day grace then downgrade.
5. Set Redis key `paypal:event:{event_id}` with TTL=7d.
6. Always return 200 (PayPal retries non-2xx for 24h).

Errors logged but never raised to PayPal — keeps webhook responsive.

### 5. UI wiring: `frontend/src/pages/parent/settings/subscription.astro`

- Remove `disabled` from upgrade button + remove "Coming soon" copy (lines 52, 85, 288).
- Add click handler that POSTs to `/api/subscriptions/checkout` with selected `{plan_name, billing_cycle}`.
- On success: `window.location.href = data.approve_url`.
- Add a small "activate" landing page at `/parent/settings/subscription/activate.astro` that reads `subscription_id` query param, POSTs `/api/subscriptions/activate`, shows success/error, redirects to `/parent/settings/subscription`.
- Add `?cancelled=1` query handler on subscription page (flash message).

### 6. Feature gating

Apply `require_feature()` dependency at four routes:

| Feature key | Type | Route(s) | Free | Plus | Pro |
|---|---|---|---|---|---|
| `receipt_scan` | metered/month | `POST /api/budget/transactions/scan-receipt` | 3 | 50 | unlimited |
| `budget_transaction` | metered/month | `POST /api/budget/transactions/` | 100 | 1000 | unlimited |
| `family_member` | metered (total) | `POST /api/invitations/`, `POST /api/families/{id}/members` | 3 | 6 | unlimited |
| `budget_reports` / `budget_goals` / `ai_features` | boolean | `GET /api/budget/reports/*`, `GET /api/budget/goals/*`, `POST /api/budget/transactions/scan-receipt` | blocked | enabled | enabled |

`require_feature()` is a FastAPI dependency. When the limit is hit it raises a new `QuotaExceededException` (subclass of `HTTPException` with `status_code=402` and a structured detail). A FastAPI exception handler registered in `app/main.py` formats the response body as:
```json
{
  "error": "quota_exceeded",
  "feature": "receipt_scan",
  "current_plan": "free",
  "limit": 3,
  "used": 3,
  "upgrade_url": "/parent/settings/subscription"
}
```
Status 402 (Payment Required).

Frontend: detect 402 in `apiFetch` wrapper → show upgrade modal globally.

## Data Model Changes

**No new tables.** All needed columns exist on `FamilySubscription`. One add:

```sql
ALTER TABLE family_subscriptions
  ADD COLUMN cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN trial_end_at TIMESTAMPTZ NULL,
  ADD COLUMN payment_failure_at TIMESTAMPTZ NULL;
```

New Alembic migration `paypal_v1_subscription_flags`.

## Data flow

```
[UI click "Upgrade Plus monthly"]
   ↓ POST /api/subscriptions/checkout {plan_name:"plus", billing_cycle:"monthly"}
[backend] resolve paypal_plan_id → PayPal createSub → insert FamilySubscription(status=pending)
   ↓ returns approve_url
[browser] redirect → PayPal hosted approval page
[user] accepts (starts 7-day trial)
[PayPal] redirect → /parent/settings/subscription/activate?subscription_id=I-XXXX
[browser → backend] POST /api/subscriptions/activate {subscription_id}
[backend] fetch sub from PayPal, update row status=trial, set period_end
[PayPal webhook ~10s later] BILLING.SUBSCRIPTION.ACTIVATED
   ↓ POST /api/subscriptions/webhook (signed)
[backend] verify sig, dedupe by event_id, reconcile FamilySubscription
[7 days later, PayPal] BILLING.SUBSCRIPTION.PAYMENT.SALE → status auto-transitions in PayPal
[every billing cycle thereafter] webhook fires on payment events
```

Cancel:
```
[UI click "Cancel"]
   ↓ POST /api/subscriptions/cancel
[backend] PayPal cancel API → set FamilySubscription.cancel_at_period_end=true
[at period_end, daily sweep job] downgrade family.plan_id → "free"
```

## Webhook security

1. **Signature verification**: PayPal signs each webhook with their cert + transmission ID. Method `verify_webhook_signature()` already in `paypal_service.py` — wire it.
2. **Idempotency**: Each PayPal event has unique `event_id`. Dedupe via Redis SET with 7-day TTL.
3. **Replay protection**: PayPal `Paypal-Transmission-Time` header — reject if > 5 min old.
4. **PAYPAL_WEBHOOK_ID** env var — created in PayPal dashboard when registering webhook URL. Must be set before webhook handler can verify.

## Testing

Unit tests:
- `test_paypal_service.py` — mock PayPal SDK. Cover: create_subscription, verify_webhook_signature happy/bad-sig, get_subscription.
- `test_subscription_routes.py` — extend existing. Add cases for checkout body validation, activate happy path + idempotency, cancel.
- `test_paypal_webhook.py` — new. Fixture JSON payloads per event type. Cover: valid sig + each event → DB state change; invalid sig → 401; duplicate event_id → 200 no-op.
- `test_premium_gating.py` — new. Cover: free plan hits limit → 402 with structured body; plus plan goes through; pro plan ignores meters.

E2E manual:
1. Run `setup-paypal-plans.py` against sandbox → paste IDs in `.env`.
2. Restart stack.
3. Sign in as Juan (PARENT), navigate `/parent/settings/subscription`, click Upgrade Plus monthly.
4. Complete sandbox PayPal checkout (use PayPal sandbox buyer account).
5. Verify redirect back, "Trial active" message, DB row `status=trial`.
6. In PayPal sandbox dashboard, trigger ACTIVATED webhook — verify DB reconciliation.
7. Click Cancel → verify `cancel_at_period_end=true`, status still trial/active until period end.

## Risks

- **PayPal sandbox flakiness**: sandbox occasionally drops webhook deliveries. Workaround: poll PayPal API on `/api/subscriptions/current` if last webhook > 1h old.
- **Webhook reachability**: PayPal must reach `https://api-gcp-family.agent-ia.mx/api/subscriptions/webhook`. CF tunnel allows this. Verify by sending test event from PayPal dashboard.
- **Trial abuse**: Same email starting multiple trials on same plan. PayPal handles this server-side (one trial per buyer per plan).
- **Currency**: hardcoded USD. Mexican market may want MXN later — design supports it (price stored cents + currency_code on `SubscriptionPlan` — already present).

## Env vars added/required

```bash
# Existing keys (already in .env.gcp.example, need values)
PAYPAL_MODE=sandbox            # sandbox first, flip to live later
PAYPAL_CLIENT_ID=<sandbox-app-client-id>
PAYPAL_CLIENT_SECRET=<sandbox-app-secret>
PAYPAL_PLAN_ID_PLUS_MONTHLY=<from setup-paypal-plans.py>
PAYPAL_PLAN_ID_PLUS_ANNUAL=<from setup-paypal-plans.py>
PAYPAL_PLAN_ID_PRO_MONTHLY=<from setup-paypal-plans.py>
PAYPAL_PLAN_ID_PRO_ANNUAL=<from setup-paypal-plans.py>
PAYPAL_WEBHOOK_ID=<from PayPal dashboard webhook creation>
```

Webhook URL to register in PayPal dashboard: `https://api-gcp-family.agent-ia.mx/api/subscriptions/webhook`
After cutover to apex: `https://api.family.agent-ia.mx/api/subscriptions/webhook`.

## Open questions (resolved)

- ✅ Sandbox-first vs live → sandbox first
- ✅ Plan creation → script via API
- ✅ Trial → 7 days
- ✅ Cancel timing → end of period
- ✅ Gating scope → all four feature classes
- ✅ Webhook events → ACTIVATED + CANCELLED + PAYMENT.FAILED
- ✅ Creds → user provides before deploy
