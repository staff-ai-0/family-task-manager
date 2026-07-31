# Coupons + PayPal price repair — design

**Date**: 2026-07-31
**Status**: approved (design), pending implementation
**Ships as**: two PRs, in order. PR 1 (PayPal repair) must land and be verified before PR 2 is useful.

---

## 1. Problem

### 1.1 Billing is dead in production

Prod (`10.1.0.91`, `family_onprem_db`) as of 2026-07-31:

```
 name | currency | price_monthly | price_annual | paypal_plan_id_monthly | paypal_plan_id_annual | is_active
 free | USD      |             0 |            0 | NULL                   | NULL                  | t
 plus | MXN      |             0 |            0 | NULL                   | NULL                  | t
 plus | USD      |             0 |            0 | NULL                   | NULL                  | t
 pro  | MXN      |             0 |            0 | NULL                   | NULL                  | t
 pro  | USD      |             0 |            0 | NULL                   | NULL                  | t
```

Three separate defects, all user-visible:

1. **Paid tiers display as $0.** `/parent/settings/subscription` renders
   `plan.price_monthly_cents ?? fallbackCents[...]`. The row exists with a
   real `0`, so the fallback never fires and the pricing table advertises
   "Plus — $0/mes".
2. **No PayPal plan is wired.** Every `paypal_plan_id_*` is NULL, so
   `POST /api/subscriptions/checkout` raises
   `501 PayPal plan not configured`. Nobody can pay, in any currency.
3. **The MXN rows are active but unwired**, which is exactly the state the
   `mxn_plan_currency_w6` migration seeded them `is_active = false` to
   avoid. The page defaults Mexico-first to MXN, computes
   `checkout_ready_monthly = false` for every paid row, and disables the
   upgrade buttons behind a "coming soon" note.

**This is not a missing migration.** Prod's alembic head is
`user_completed_tours`, which is downstream of `usd_price_alignment`
(plus 500/5000, pro 1500/15000) and `mxn_plan_currency_w6` (plus
9900/99000, pro 19900/199000). Both ran. `updated_at` on all four paid rows
is `2026-07-16 17:30:11.67115+00` — a single transaction, consistent with
that upgrade run — and no migration in the chain ever writes a `0` price.
The rows were therefore overwritten out-of-band after the fact (manual SQL,
a restore, or a script run against prod). The audit trail does not cover
`subscription_plans`, so the actor is not recoverable.

The design consequence: **restoring the values is not enough** — the same
out-of-band write can happen again and would again go unnoticed for weeks.
PR 1 restores *and* makes recurrence loud.

### 1.2 No way to give the product away

Launch and mass testing need "one month free" / "extended trial" codes. The
only credit mechanism today is:

- `families.referral_bonus_until` — a single nullable timestamp. While it is
  in the future, `premium.get_family_plan_by_id` floors the family at Plus.
- Written by `ReferralService` (stacks +30d per referral) and by the
  operator action `AdminActionService.comp_plus_month` (absolute "Plus until
  X").

It is **Plus-only, single-window, non-revocable, non-auditable per grant**,
and has no notion of a code a user can type. It cannot express "90 days of
Pro", "lifetime comp for my brother", or "who redeemed LANZAMIENTO2026".

---

## 2. Decisions taken

| Question | Decision |
|---|---|
| Coupon mechanism | **Internal credit only** — no PayPal call, no card. Works today even with checkout broken. |
| Coupon kinds at launch | Free period at a tier · extended trial (beta) · lifetime comp |
| Percent/amount off | **Phase 2**, after live billing is verified with a real payment. Reserved (nullable) columns now so the schema does not churn. |
| Redeem surfaces | Settings → Subscription box **and** `?coupon=CODE` at registration |
| Coupon authoring | Superadmin console UI (`/admin/coupons`), audited |
| PayPal repair scope | Restore prices + re-provision at live PayPal + wire ids + guard against recurrence |
| Currencies at launch | MXN **and** USD both checkout-able |
| Existing credit mechanisms | **Unify** — referral and operator comp move onto the new grants table; `families.referral_bonus_until` is backfilled and dropped |

Explicitly out of scope: Stripe (never), proration, refunds, gifting a
subscription to another family, coupon stacking rules beyond the additive
rule in §4.3.

---

## 3. PR 1 — PayPal price repair

### 3.1 Single source of truth for prices

Prices are currently duplicated in **three** places, with a comment in each
begging the reader to keep them in sync:

- `backend/scripts/setup_paypal_plans.py` → `PLAN_PRICES`
- `backend/migrations/versions/2026_07_08_mxn_plan_currency_w6.py` →
  `MXN_PRICES`, and `2026_07_16_usd_price_alignment.py` → `USD_PRICES`
- `frontend/src/pages/parent/settings/subscription.astro` → `fallbackCents`

New module `backend/app/core/plan_pricing.py`:

```python
# (tier, currency) -> (monthly_minor_units, annual_minor_units)
CANONICAL_PRICES: dict[tuple[str, str], tuple[int, int]] = {
    ("plus", "USD"): (500, 5_000),
    ("pro",  "USD"): (1_500, 15_000),
    ("plus", "MXN"): (9_900, 99_000),
    ("pro",  "MXN"): (19_900, 199_000),
}
```

- `setup_paypal_plans.py` imports it and derives its PayPal decimal strings
  from it (`f"{minor/100:.2f}"`), deleting `PLAN_PRICES`.
- The repair migration (§3.2) imports it. Migrations normally must not
  import app code (it can drift under them), so the migration copies the
  literal table into its own module-level constant *and* a test asserts the
  two are equal — the migration stays self-contained and frozen, the drift
  is caught in CI rather than at `alembic upgrade` time.
- `fallbackCents` in the frontend is **deleted**. A missing plan row now
  renders `—` and disables the upgrade button, instead of confidently
  printing a price the backend never confirmed. This removes the third copy
  and the class of bug where the UI advertises a price nobody can be
  charged.

### 3.2 Repair migration

`backend/migrations/versions/2026_07_31_restore_plan_prices.py`

- `upgrade()`: for each `(tier, currency)` in the frozen canonical table,
  `UPDATE subscription_plans SET price_monthly_cents = …,
  price_annual_cents = …, updated_at = now() WHERE name = … AND currency = …`.
  Absolute, not conditional — idempotent, and re-running always converges.
- `downgrade()`: no-op with an explanatory docstring. Prices are display
  data with a single correct value; there is no meaningful earlier state to
  return to, and reverting to `0` would recreate the outage. (CI runs
  upgrade → downgrade -1 → upgrade, so the no-op must be genuinely safe —
  it is: the following upgrade re-asserts the same values.)
- Deliberately does **not** touch `is_active` or `paypal_plan_id_*`. Those
  are provisioning state (§3.4), owned by the operator run, and a migration
  that flipped them would fight the script.

### 3.3 Make recurrence loud

Three layers, cheapest first:

1. **CI regression test** — `backend/tests/test_plan_pricing_invariants.py`:
   - every active plan row whose `name != "free"` has
     `price_monthly_cents > 0` and `price_annual_cents > 0`;
   - every such row matches `CANONICAL_PRICES` exactly;
   - the migration's frozen copy equals `CANONICAL_PRICES`.
   Runs against the migrated test DB, so a future migration (or a seed
   script) that zeroes a price fails the build.
2. **Operator console health panel** — the admin overview gains a "Billing
   configuration" block listing any active paid row with a zero price or a
   NULL `paypal_plan_id_*`, red when non-empty. Read-only, reuses
   `admin_read_service`. This is the layer that would have caught the live
   incident: CI cannot see prod's data.
3. **Startup warning** — `app/main.py` startup logs a single
   `logger.error("billing misconfigured: …")` line listing offending rows.
   Free, and it lands in `podman logs` where the deploy smoke check can grep
   it later if we want to escalate.

### 3.4 Provisioning at PayPal (operator step, live)

`scripts/setup_paypal_plans.py` is idempotent: it looks up product and plans
**by name across all pages** and creates only what is missing. Sequence:

1. `--dry-run` in the prod container → review the 8 plans and their prices
   with the user before any write.
2. Live run: `podman exec family_onprem_backend python -m
   scripts.setup_paypal_plans` with `PAYPAL_MODE=live` from the container
   env. Prints env lines and the wiring SQL.
3. Apply the printed SQL against `family_onprem_db`. It sets
   `paypal_plan_id_{monthly,annual}` and `is_active = true` per
   `(name, currency)`.
4. If MXN plan creation 400s (the PayPal business account must be
   Mexico-registered to price in MXN), fall back to: USD wired and active,
   MXN rows set `is_active = false` so nothing lands on an un-checkout-able
   price. This is a decision point to surface to the user, not to paper over.

### 3.5 Verification (PR 1 done means)

- `GET /api/subscriptions/plans` returns non-zero prices and
  `checkout_ready_monthly = checkout_ready_annual = true` for all four paid
  rows.
- `/parent/settings/subscription` shows MX$99 / MX$199 (and US$5 / US$15 on
  the USD toggle), with enabled upgrade buttons and no "coming soon" note.
- `POST /api/subscriptions/checkout` returns a real PayPal approval URL
  (creating a subscription does not charge — the buyer must approve).
- Completing a real payment is the user's click; the design does not claim
  it as verified until they do.

---

## 4. PR 2 — Coupons

### 4.1 Data model

**`coupons`** — the code an operator authors.

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `code` | `varchar(32)` UNIQUE NOT NULL | stored upper-case; `^[A-Z0-9][A-Z0-9-]{3,31}$` |
| `kind` | `varchar(20)` NOT NULL | `launch` \| `beta` \| `comp` — reporting label only; see §4.2 |
| `tier` | `varchar(20)` NOT NULL | `plus` \| `pro` — the tier the credit floors at |
| `duration_days` | `int` NULL | NULL ⇒ lifetime |
| `max_redemptions` | `int` NULL | NULL ⇒ unlimited |
| `redemption_count` | `int` NOT NULL default 0 | denormalized counter, see §4.4 |
| `valid_from` | `timestamptz` NULL | NULL ⇒ immediately |
| `valid_until` | `timestamptz` NULL | NULL ⇒ never expires |
| `is_active` | `bool` NOT NULL default true | operator kill-switch |
| `campaign` | `varchar(120)` NULL | free-text grouping ("Lanzamiento MX", "Beta testers") |
| `notes` | `varchar(500)` NULL | operator-facing |
| `created_by_user_id` | UUID FK users NULL | `ON DELETE SET NULL` |
| `discount_percent` | `int` NULL | **phase 2**, unused |
| `discount_amount_cents` | `int` NULL | **phase 2**, unused |
| `discount_cycles` | `int` NULL | **phase 2**, unused |
| `created_at` / `updated_at` | `timestamptz` | |

`coupons` is intentionally **not** family-scoped — it is an operator-owned,
cross-tenant catalog, in the same category as `subscription_plans`. All
reads/writes go through `require_superadmin` except the redeem path, which
looks a code up by exact match and never lists.

**`plan_credit_grants`** — one row per credit window actually given to a
family. This is the single credit mechanism (§4.5).

| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `family_id` | UUID FK families NOT NULL | `ON DELETE CASCADE`, indexed |
| `source` | `varchar(20)` NOT NULL | `coupon` \| `referral` \| `operator` |
| `coupon_id` | UUID FK coupons NULL | `ON DELETE SET NULL`; set iff `source = 'coupon'` |
| `tier` | `varchar(20)` NOT NULL | `plus` \| `pro` |
| `starts_at` | `timestamptz` NOT NULL | |
| `ends_at` | `timestamptz` NULL | NULL ⇒ lifetime |
| `revoked_at` | `timestamptz` NULL | soft revoke, preserves the audit trail |
| `granted_by_user_id` | UUID FK users NULL | operator grants |
| `reason` | `varchar(500)` NULL | required for operator grants |
| `created_at` | `timestamptz` | |

Constraints:

- `UNIQUE (family_id, coupon_id)` — **the anti-double-redeem guard, at the
  DB level**, mirroring `uq_referrals_referred_family`. Two concurrent
  redeems of the same code by the same family: one wins, the other gets an
  `IntegrityError` the service maps to `already_redeemed`. (Postgres treats
  NULLs as distinct, so this does not constrain non-coupon grants — correct:
  a family may hold many referral/operator grants.)
- Partial index `(family_id) WHERE revoked_at IS NULL` for the resolution
  query.

### 4.2 On `kind`

`launch`, `beta` and `comp` share one mechanic: *N days (or forever) at
tier T*. `kind` carries no behavior — it exists so the operator can filter
"show me every beta-tester family" and so reporting can separate a launch
promo from a friends-and-family comp. This is deliberate: a behavioral
distinction that does not exist should not be modeled as one, but the
operator's need to group them is real. Documented on the column so nobody
later writes `if kind == "beta"` logic into the resolution path.

### 4.3 Grant windows and stacking

Redeeming a coupon creates one grant:

```
starts_at = max(now, latest ends_at among the family's active,
                non-lifetime grants)          # additive, never overlapping
ends_at   = starts_at + duration_days         # or NULL for lifetime
```

This is the rule `ReferralService` already uses (a payer's credit begins
after the period they already paid for, so it is genuinely additive rather
than burned in parallel with paid time). Reusing it keeps one mental model.

A lifetime grant sets `ends_at = NULL` and does not shift subsequent
windows (there is nothing to queue behind).

### 4.4 `redemption_count`

Denormalized on `coupons` for cheap "142 / 500 used" display. It is a
**counter, not the source of truth** — the authoritative count is
`SELECT count(*) FROM plan_credit_grants WHERE coupon_id = …`. The redeem
path increments it inside the same transaction as the grant insert, using
`UPDATE coupons SET redemption_count = redemption_count + 1 WHERE id = …
AND (max_redemptions IS NULL OR redemption_count < max_redemptions)` and
treating a 0-row result as `coupon_exhausted`. That makes the cap race-free
without a `SELECT … FOR UPDATE`, since the UPDATE takes the row lock and
re-checks the predicate atomically. The admin redemption list reads the
authoritative count so a drifted counter is visible.

### 4.5 Plan resolution (the unification)

`premium.get_family_plan_by_id` today does: entitled subscription → Plus
floor if `families.referral_bonus_until` is future → DB free row →
hardcoded defaults.

After this PR:

1. Entitled subscription (unchanged).
2. **Credit floor** — one query for the family's active grants:
   `revoked_at IS NULL AND starts_at <= now() AND (ends_at IS NULL OR
   ends_at > now())`. Floor tier = highest `PLAN_ORDER` among them.
3. If a paid plan resolved and its rank ≥ floor rank, the paid plan wins;
   otherwise the floor's plan row is returned (same `_plus_floor_plan`
   shape, generalized to `_tier_floor_plan(tier)`).
4. Free row → hardcoded defaults (unchanged).

Query count is unchanged: the `referral_bonus_until` scalar select is
replaced by the grants select.

**Migration of the existing mechanism**, in one alembic revision:

- Backfill: every family with `referral_bonus_until` in the future gets one
  grant `(source='referral', tier='plus', starts_at=now(),
  ends_at=referral_bonus_until)`. Past/NULL values are dropped — they grant
  nothing today, and inventing historical windows would fabricate an audit
  trail. Note this in the migration docstring.
- `ReferralService._grant_referral_month` writes a grant instead of
  advancing the timestamp; its stacking becomes §4.3's rule (same result).
- `AdminActionService.comp_plus_month` becomes `grant_plan_credit(tier,
  days | lifetime, reason)` — the operator gains Pro comps, lifetime comps
  and revoke, which it cannot do today. Route
  `POST /api/admin/families/{id}/comp-plus` is kept as-is in shape (so the
  existing admin UI keeps working) and a superset route is added.
- `families.referral_bonus_until` is **dropped** in the same revision.
  Downgrade re-adds the column and re-derives it from the latest active
  Plus grant, so the round-trip CI gate passes.

### 4.6 API

Family-facing (`/api/subscriptions/`), all `require_parent_role`:

- `POST /coupons/redeem` `{code}` →
  `{tier, starts_at, ends_at, lifetime, coupon: {code, kind, campaign}}`.
  Rate-limited via the existing slowapi `limiter` (`10/hour` per IP).
  Launch codes are human-chosen and therefore guessable by design
  (`LANZAMIENTO`, `BETA2026`) — the rate limit only slows enumeration; the
  actual blast-radius controls are `max_redemptions`, `valid_until` and
  one-grant-per-family.
  **Uniform error**: every rejection (unknown code, inactive, outside
  validity window, exhausted) returns
  `404 {"error": "invalid_or_expired_coupon"}`, so the endpoint is not an
  oracle for which codes exist. The single exception is
  `409 {"error": "already_redeemed"}` — the family already holds this
  coupon's grant, which they can see anyway, and a uniform 404 there would
  be actively confusing.
- `GET /credits` → active grants for the family (tier, ends_at, lifetime,
  source) so the UI can render the banner. Returns `[]` for families with
  none.

Operator (`/api/admin/`), all `require_superadmin`, all audited via
`OperatorAuditService` on the same session as the mutation (the existing
`AdminActionService` staging pattern):

- `GET /coupons` — list + filters (`is_active`, `kind`, `campaign`)
- `POST /coupons` — create (`coupon.create`)
- `PATCH /coupons/{id}` — `is_active`, `valid_until`, `max_redemptions`,
  `notes` only. Code, tier and duration are immutable once created: mutating
  them would retroactively change what already-issued grants meant.
  (`coupon.update`)
- `GET /coupons/{id}/redemptions` — the grants, with family name/id
- `POST /families/{id}/credits` — direct grant (`family.grant_credit`)
- `POST /credits/{grant_id}/revoke` — sets `revoked_at`
  (`family.revoke_credit`, reason required)

### 4.7 Registration path

`?coupon=CODE` on the register page → `RegisterRequest.coupon` (same shape
as the existing `ref` field). Applied **only on the new-family path**
(`not data.family_code and pending_invite is None`), immediately after the
referral block, with the same best-effort contract: a failed coupon never
breaks signup, and a failure rolls the session back so the rest of
registration (email send, token issue) still works.

The register response gains `coupon_applied: bool` so the post-signup screen
can say "Cupón LANZAMIENTO aplicado — 30 días de Plus gratis" or, honestly,
say nothing when the code was bad. Silently swallowing a mistyped launch
code is the failure mode most likely to generate support mail.

### 4.8 Frontend

- `/parent/settings/subscription`:
  - **Active credit banner** above the plan comparison when
    `GET /credits` is non-empty: *"Plus gratis hasta el 30 de septiembre"* /
    *"Pro de por vida"*, with the source (referral vs coupon vs cortesía).
  - **Redeem box** — `¿Tienes un cupón?` input + button, parent-only,
    optimistic-free (it re-fetches on success, per the mutate() pattern the
    UX audit standardized). Inline error text for the two error codes.
- `/register` reads `?coupon=` into a hidden field, and shows the applied /
  not-applied result on the success screen.
- `/admin/coupons` — list with redemption counts, create form, deactivate,
  drill into redemptions. Follows `admin/families.astro` conventions;
  behind the same Cloudflare Access path policy as the rest of `/admin/*`.
- i18n: ES + EN inline, matching the surrounding pages (the repo's known
  i18n debt is out of scope here — do not refactor).

### 4.9 Tests

- **Coupon validation matrix** — unknown / inactive / not-yet-valid /
  expired / exhausted / already-redeemed, each asserting the exact error
  contract in §4.6 (including that four of them are indistinguishable).
- **Grant windows** — additive stacking off an existing grant; lifetime
  grant; grant starting after a paid period.
- **Concurrency** — two simultaneous redeems of the same code by one family
  produce exactly one grant (unique constraint); N concurrent redeems of a
  `max_redemptions = 1` coupon by different families produce exactly one.
- **Resolution** — a Pro grant beats a Plus paid sub; a Pro paid sub beats a
  Plus grant; a revoked grant grants nothing; an expired grant grants
  nothing.
- **Gating regression** — a free family with a Plus coupon passes
  `require_feature("ai_features")` and loses it once the grant expires.
  Extends `test_ai_gating.py` rather than duplicating it.
- **Referral parity** — the existing `test_referral.py` suite must pass
  unchanged against the grants implementation. This is the primary safety
  net for the unification; if it needs edits, the edits are the review
  surface.
- **Admin authz** — every new admin route 404s for a non-superadmin
  (`test_admin_authz.py` pattern), and writes an audit row on success.
- **Migration round-trip** — upgrade → downgrade → upgrade with a family
  holding a future `referral_bonus_until`, asserting the value survives.
- **Registration** — `?coupon=` on the new-family path grants; on the
  join-by-code path does not; a bad code still registers the user.

### 4.10 Multi-tenancy note

`plan_credit_grants` carries `family_id` and every family-facing read filters
by the caller's `family_id` from the JWT, per the project's isolation rule.
`coupons` is the sanctioned cross-tenant exception (operator catalog), reached
only through `require_superadmin` — the same category as `subscription_plans`,
and the same rule as `app/services/admin/`: no `verify_family_id` /
`get_family_user` on those routes.

---

## 5. Sequencing

1. **PR 1** — pricing single-source, repair migration, invariants test,
   admin health panel, startup warning. Deploy. Then the operator
   provisioning run (§3.4) against live PayPal, with the dry-run reviewed
   first.
2. **Verify** — §3.5, including a real payment by the user.
3. **PR 2** — coupons + grants unification.
4. **Phase 2 (not in this design)** — percent/amount-off coupons via PayPal
   plan-override at subscription-create, once live billing has proven
   itself.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Live PayPal plan creation charges nobody but is hard to undo (plans cannot be deleted, only deactivated) | Dry-run reviewed with the user first; the script matches existing plans by name across all pages, so a re-run does not duplicate |
| MXN plan creation rejected by the PayPal account | Documented fallback in §3.4: USD live, MXN rows deactivated — never left active-and-unwired |
| Dropping `referral_bonus_until` loses credit for a family mid-window | Backfill runs in the same transaction as the drop; downgrade re-derives the column; round-trip test with a live future value |
| A coupon grant silently upgrades a family past what an operator intended | Every grant is a row with `source`, `granted_by_user_id`, `reason` and a revoke path; operator actions are in `operator_audit_log` |
| The zeroing that caused §1.1 recurs | Three detection layers (§3.3); the DB-level one (admin panel) is the one that would have caught the actual incident |
