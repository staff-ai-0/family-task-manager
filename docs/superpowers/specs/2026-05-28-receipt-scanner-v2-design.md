# Receipt Scanner v2 — Zero-Friction One-Tap + Structured Items

**Date:** 2026-05-28
**Status:** Design — pending user approval
**Author:** Brainstormed via Claude Code (Opus 4.7)
**Supersedes:** `docs/2026-04-01-ux-enhancements-design.md` §receipt-scanner only. Original scanner spec `docs/2026-04-02-receipt-scanner-design.md` remains the v1 reference.

---

## 1. Goal

Turn the receipt scanner from a "snap then fill in the rest" form into a one-tap experience where the user snaps and confirms. Everything else — account, payee, per-item categorization, duplicate detection, FX cross-charge, tax breakout, price-history trend — is inferred from the image. Side-effects (shopping list reconciliation, external price-comparison agent) fan out automatically.

Non-goal: replace the human-in-the-loop (HITL) draft review queue. Low-confidence scans still route there unchanged.

## 2. User-visible outcome

1. Tap `Snap Receipt` → camera opens. No account dropdown to pre-pick.
2. Take photo. Full-screen scan animation, ~3–5 s.
3. Confirm card slides up with merchant logo, total (with FX line if cross-currency), auto-picked account (`Mastercard **9222 ✓` or `(last used)` amber dot if fallback), itemized list with inline price-trend badges (`📈 +14%` / `📉 -8%`), and an IVA pill when applicable.
4. Default action: `Looks good — save`. Single tap. Done.
5. If the system thinks it's a duplicate of a scan made in the last 60 s: modal with `Open original` / `Save anyway`.

A side-channel webhook fires asynchronously to an external price-comparison agent (configured per family).

## 3. Architecture

Single-call extension of the current `POST /api/budget/transactions/scan-receipt` endpoint. No two-stage commit, no optimistic write. All stages execute server-side inside the request, except the webhook fan-out which is dispatched to a background task after commit.

```
[client]
   │  multipart upload (image|pdf) + optional account_id override + force=bool
   ▼
POST /api/budget/transactions/scan-receipt
   │
   ├─► (1) Vision extract  (LiteLLM → claude-haiku)
   │         richer prompt: + card_last4, + iva_cents, + per-item qty/unit_price,
   │         + brand, + currency (already), + fx_hint
   │
   ├─► (2) Account auto-detect
   │         match BudgetAccount.card_last4 within family
   │         on >1 hit → narrow by currency (receipt.currency == account.currency)
   │         on 0 hits → fallback: account from the most-recent transaction created
   │                     by the currently-authenticated user within this family
   │         on 0 hits AND non-Pro caller AND receipt.currency ≠ fallback.currency:
   │           route to HITL drafts queue with reason "currency_mismatch"
   │         caller's account_id override (when valid for the family) always wins
   │
   ├─► (3) Duplicate guard
   │         payee_name from vision is first resolved to a payee_id via the
   │         existing find-or-create step. Then:
   │         same family + same resolved payee_id + |total| within 1% + within 60s
   │         → return 409 { dup_warning: {existing_transaction_id, scanned_at} }
   │           with the scanned blob (no commit; payee is rolled back) so the
   │           client can show the modal
   │         → caller re-POSTs with ?force=true to commit anyway
   │
   ├─► (4) FX cross-charge
   │         when receipt.currency != account.currency:
   │           fx_rate = FXService.get(receipt.currency → account.currency, on=receipt.date)
   │           account_total = round(receipt.total * fx_rate)
   │         on FX failure: keep receipt currency, set fx_rate=null, attach soft warning
   │
   ├─► (5) Persist
   │         BudgetTransaction (existing + new cols: card_last4, iva_cents,
   │                            fx_rate, original_amount_cents, original_currency)
   │         BudgetTransactionItem[] (new table, see §4)
   │
   ├─► (6) Auto-categorize
   │         CategorizationRuleService.suggest_category on (payee, item.name)
   │         applied per item AND for the transaction header (header = most common item category)
   │
   └─► (7) Post-commit fan-out (BackgroundTasks):
           ├─ shopping auto-check (existing _auto_check_shopping_items)
           └─ a2a webhook enqueue (new) — write row to a2a_webhook_deliveries,
              dispatch HTTP POST inline once, schedule retries if it fails
```

Low-confidence path (`confidence < 0.3` OR no detectable total) keeps the existing HITL `BudgetReceiptDraft` route — none of the above stages run for those.

## 4. Data model

### 4.1 New table — `budget_transaction_items`

| column | type | nullable | notes |
|---|---|---|---|
| `id` | `uuid` | no | pk, default `uuid4()` |
| `family_id` | `uuid` | no | fk `families.id` ON DELETE CASCADE — tenant guard, indexed |
| `transaction_id` | `uuid` | no | fk `budget_transactions.id` ON DELETE CASCADE |
| `name` | `text` | no | as printed on receipt |
| `normalized_name` | `text` | no | lowercased, accents stripped, unit suffixes (`kg`, `lt`, `pza`, `g`) trimmed; used for cross-transaction trend lookups |
| `qty` | `numeric(10,3)` | yes | |
| `unit_price_cents` | `bigint` | yes | absolute value (positive). `null` when receipt only printed line totals |
| `total_cents` | `bigint` | no | absolute value (positive). `transaction.amount` remains the single source of truth for net effect; item totals are display + analytics |
| `category_id` | `uuid` | yes | fk `budget_categories.id` ON DELETE SET NULL — per-item category (independent of header) |
| `brand` | `text` | yes | when vision can guess |
| `raw_text` | `text` | yes | original line as printed (preserved for audit / future re-parse) |
| `created_at` | `timestamptz` | no | `default now()` |
| `updated_at` | `timestamptz` | no | `default now()`, `onupdate now()` |

Indexes:
- `(family_id, normalized_name, created_at desc)` — trend lookup
- `(transaction_id)` — join
- `(family_id, category_id)` — per-category rollups

### 4.2 New columns on `budget_transactions`

| column | type | nullable | notes |
|---|---|---|---|
| `card_last4` | `char(4)` | yes | what vision saw, kept for audit even when auto-detect missed |
| `iva_cents` | `bigint` | yes | Mexican tax line, absolute value |
| `fx_rate` | `numeric(12,6)` | yes | rate from `original_currency` → `transaction.account.currency`, on the date of the receipt |
| `original_amount_cents` | `bigint` | yes | total before FX, in `original_currency`. negative for expenses, like `transaction.amount` |
| `original_currency` | `char(3)` | yes | ISO 4217 |

### 4.3 New column on `budget_accounts`

| column | type | nullable | notes |
|---|---|---|---|
| `card_last4` | `char(4)` | yes | partial index: `WHERE card_last4 IS NOT NULL` |

Composite index `(family_id, card_last4)` (partial, `card_last4 IS NOT NULL`).

Backfill in migration: regex `(?:\*{2,}|terminada en )(\d{4})` against `BudgetAccount.name`. Hits go into `card_last4`. The 17 real-prod accounts (e.g. `Cheques Banamex ***313`, `Mastercard **9222 (USD)`) cover the format we see in the wild.

### 4.4 New table — `family_a2a_webhooks`

One row per family. Per-family opt-in.

| column | type | notes |
|---|---|---|
| `family_id` | `uuid` | pk, fk `families.id` ON DELETE CASCADE |
| `url` | `text` | https only, validated on PUT |
| `secret` | `text` | random 32-byte hex; used for HMAC-SHA256 signature header |
| `enabled` | `bool` | default `false` |
| `last_success_at` | `timestamptz` | nullable |
| `last_error` | `text` | nullable, truncated to 500 chars |
| `failure_count` | `int` | rolling, reset on success |
| `created_at`, `updated_at` | `timestamptz` | |

### 4.5 New table — `a2a_webhook_deliveries` (retry log)

| column | type | notes |
|---|---|---|
| `id` | `uuid` | pk |
| `family_id` | `uuid` | fk + tenant guard, indexed |
| `transaction_id` | `uuid` | fk `budget_transactions.id` ON DELETE CASCADE |
| `payload_json` | `jsonb` | webhook body |
| `status` | `text` | `pending` / `sent` / `failed` / `dead` |
| `attempts` | `int` | default 0, max 5 → `dead` |
| `next_retry_at` | `timestamptz` | indexed `WHERE status IN ('pending','failed')` |
| `last_error` | `text` | nullable |
| `created_at`, `updated_at` | `timestamptz` | |

Backoff schedule: `+1m, +5m, +30m, +2h, +12h`. After the 5th attempt, status → `dead`.

### 4.6 Alembic migration

`backend/alembic/versions/wave4_scanner_v2.py`. Adds all five table/column changes above and backfills `budget_accounts.card_last4` in the upgrade body.

## 5. API surface

### 5.1 Extended — `POST /api/budget/transactions/scan-receipt`

Request: multipart `image` (existing) + new query/form params:

| param | type | default | notes |
|---|---|---|---|
| `account_id` | `uuid?` | inferred | override auto-detect |
| `force` | `bool` | `false` | skip duplicate guard |

Response (`200 OK`, success commit):

```json
{
  "success": true,
  "transaction_id": "uuid",
  "transaction": { ...existing TransactionRead... },
  "items": [ ...TransactionItemRead[]... ],
  "account_match": { "strategy": "card_last4" | "last_used" | "override",
                     "matched_card_last4": "9222" | null },
  "fx": { "rate": 17.15, "original_amount_cents": -4200,
          "original_currency": "USD" } | null,
  "trends": [ { "normalized_name": "leche alpura", "avg_unit_cents": 2800,
                 "last_unit_cents": 3200, "pct_change": 0.142,
                 "sample_size": 8 } ],
  // trends array contains one entry per item where sample_size >= 3;
  // items below threshold are omitted, not included with nulls
  "confidence": 0.91,
  "shopping_auto_checked": ["Leche", "Pan integral"]
}
```

Response (`409 Conflict`, duplicate detected, no commit):

```json
{
  "success": false,
  "dup_warning": {
    "existing_transaction_id": "uuid",
    "scanned_at": "2026-05-28T20:14:08Z",
    "payee": "HEB",
    "amount_cents": -72040
  },
  "scanned_preview": { ...what would have been written... }
}
```

Response (`200 OK`, low confidence → HITL draft): unchanged from today.

### 5.2 New — items endpoints

- `GET /api/budget/items?normalized_name=...&since=YYYY-MM-DD&limit=50` — paged history
- `GET /api/budget/items/trend?normalized_name=...&window_days=90` — `{ avg_unit_cents, last_unit_cents, pct_change, sample_size }`. `sample_size < 3` → `null` returned (no badge).
- `GET /api/budget/items/{id}` — single item
- Items are not directly editable (they reflect what was scanned). Re-scanning a transaction is the path to fix them; a follow-up release can add inline edit.

### 5.3 New — webhook config

- `GET /api/budget/a2a-webhook` — parent only. Returns `{ url, enabled, last_success_at, failure_count }` (secret is write-only).
- `PUT /api/budget/a2a-webhook` — parent only. Body `{ url, enabled, rotate_secret: bool }`. On `rotate_secret=true`, generate a new secret and return it once in the response (the only time it's exposed in plaintext).

### 5.4 New — internal retry sweep

- `POST /api/internal/a2a/retry` — protected by an internal token. Sweeps `a2a_webhook_deliveries WHERE status IN ('pending','failed') AND next_retry_at <= now()`. Called by an external cron OR a FastAPI background scheduler (`apscheduler` is already in deps — check `backend/requirements.txt`; add if missing).

### 5.5 Schema additions

`BudgetAccount` Pydantic schemas (`Create`, `Update`, `Read`) gain `card_last4: Optional[str]` with pattern `^\d{4}$`.

New schemas:
- `TransactionItemRead`
- `ItemTrend`
- `A2AWebhookRead`, `A2AWebhookUpdate`
- `DupWarning`

## 6. Frontend UX

### 6.1 `/budget/scan-receipt` redesign

Initial state: no account picker. Two CTAs only.

```
┌──────────────────────────────┐
│   Scan Receipt               │
│                              │
│   [   📷  Snap Receipt   ]   │ ← primary, orange, full-width
│   [   ⬆️  Upload Image   ]   │ ← secondary
└──────────────────────────────┘
```

Snap → `<input type=file accept="image/*,application/pdf" capture=environment>` opens native camera immediately.

While the request is in flight, full-screen overlay:

```
   [thumbnail with shimmer]

   Reading…
   Matching account…
   Categorizing items…
   Checking duplicates…
```

Stages tick forward at fixed intervals (~700 ms each) regardless of actual server timing — UX-only animation.

### 6.2 Confirm card (post-success)

```
┌────────────────────────────────────────┐
│  [HEB logo]   HEB                      │
│                                        │
│  $720.40 MXN                           │
│  ≈ $42.00 USD  @ 17.15 (May 28)        │  ← only if FX
│                                        │
│  Account                               │
│   ✓ Mastercard **9222                  │
│                                        │
│  IVA  $96.83                           │  ← pill, only if iva_cents
│                                        │
│  ─ Items ───────────────────────       │
│   Leche Alpura 1L   2 × $32.00  $64.00 │
│     📈 +14% vs 90d avg                 │
│   Pan integral      1 × $48.50  $48.50 │
│   Aguacate Hass     3 × $24.00  $72.00 │
│     📉 -8% vs 90d avg                  │
│   …                                    │
│                                        │
│  [  ✓ Looks good — save  ]             │ ← primary (no-op, already saved)
│  [ Edit ]   [ Delete & re-scan ]       │
└────────────────────────────────────────┘
```

Important: the transaction is already committed at this point. `Looks good — save` is a no-op that returns to `/budget/transactions`. `Delete & re-scan` issues `DELETE /api/budget/transactions/{id}` and pops the user back to the snap screen.

Trend badges only render when `trends[]` includes an entry for that `normalized_name` AND `sample_size >= 3`. Color: red `+`, green `−`, gray neutral (`|pct_change| < 5%`).

Account row shows a checkmark when `account_match.strategy == "card_last4"`, an amber dot + `(last used)` when `last_used`, and a black filled dot + `(you picked)` when `override`.

### 6.3 Duplicate modal

When `409 dup_warning` returns, the client shows:

```
   ⚠ Already scanned

   HEB, $720.40, 30 seconds ago.

   [ Open original ]   [ Save anyway ]
```

`Save anyway` re-POSTs the same FormData with `?force=true`.

### 6.4 New page — `/budget/items/[normalized_name]`

List view of every `BudgetTransactionItem` matching `normalized_name` for the family. Mini sparkline of `unit_price_cents` over time at the top. Tap any row → its parent transaction. Reached by tapping any item line in the confirm card or from transaction detail.

### 6.5 New settings page — `/parent/settings/a2a`

Parent-only.

```
┌──────────────────────────────────────┐
│  Price Agent (external)              │
│                                      │
│  Webhook URL  [ https://…         ]  │
│  [ x ] Enabled                       │
│                                      │
│  Secret  ••••••••••  [ Rotate ]      │
│  Last success: 2 min ago             │
│  Failures (rolling): 0               │
│                                      │
│              [ Save ]                │
└──────────────────────────────────────┘
```

### 6.6 Nav

No new top-level nav entry. The items list page is reached contextually from the confirm card and transaction detail. The webhook setting lives under existing `/parent/settings/`.

### 6.7 i18n

All new strings go through the existing i18n bundles (`frontend/src/i18n/*`). The W1–W6 inline-ternary debt called out in `project_i18n_debt.md` is NOT addressed here; new strings use the same inline ternary pattern as the rest of `/budget/*` for consistency, with a TODO referencing that memo.

## 7. Webhook contract — `family-budget.receipt.v1`

`POST {url}` with headers:

| header | value |
|---|---|
| `Content-Type` | `application/json` |
| `X-A2A-Signature` | `sha256=<hex(hmac-sha256(secret, body))>` |
| `X-A2A-Delivery` | `<a2a_webhook_deliveries.id>` |
| `X-A2A-Schema` | `family-budget.receipt.v1` |

Body:

```json
{
  "schema": "family-budget.receipt.v1",
  "family_id": "uuid",
  "transaction_id": "uuid",
  "occurred_at": "2026-05-28T20:15:38Z",
  "payee": "HEB",
  "currency": "MXN",
  "total_cents": -72040,
  "iva_cents": 9683,
  "items": [
    {
      "name": "Leche Alpura 1L",
      "normalized_name": "leche alpura",
      "qty": 2,
      "unit_price_cents": 3200,
      "total_cents": 6400,
      "category": "Groceries",
      "brand": "Alpura"
    }
  ],
  "location_hint": null
}
```

`location_hint` reserved for a follow-up release (could be filled by geocoding the merchant address line if the vision model returns it). Always `null` in v1 of the webhook schema.

Success: any 2xx response within 10 s. Anything else → retry per backoff schedule.

## 8. Vision prompt change

Replace the current `RECEIPT_PROMPT` with one that requests the new fields. JSON contract:

```json
{
  "date": "YYYY-MM-DD | null",
  "total_amount": <int cents, negative>,
  "iva_cents": <int cents, positive | null>,
  "payee_name": "string | null",
  "card_last4": "4-digit string | null",
  "currency": "ISO-4217 | null",
  "items": [
    {
      "name": "string",
      "qty": <number | null>,
      "unit_price_cents": <int positive | null>,
      "total_cents": <int positive>,
      "brand": "string | null",
      "raw_text": "string"
    }
  ],
  "confidence": <0.0–1.0>
}
```

Rules added to the prompt:
- Look for the card line: `**1234`, `XXXX1234`, `terminada en 1234`, `Card: ...1234`. Extract last 4 digits as `card_last4`.
- Look for tax line: `IVA`, `Tax`, `Impuesto`. Extract as `iva_cents` (positive integer cents).
- For each item: extract qty when explicit (`2 x` or `2 PZA`), brand when present, and the original line as `raw_text`.

## 9. New / changed services

- `app/services/budget/receipt_scanner_service.py` — extend `scan_receipt` to parse the new fields; extend `scan_and_create_transaction` with the 7 stages.
- `app/services/budget/account_matching_service.py` (new) — `match_account(family_id, card_last4, receipt_currency, fallback_user_id)`.
- `app/services/budget/duplicate_guard_service.py` (new) — `check_duplicate(family_id, payee_id, amount_cents)`.
- `app/services/budget/transaction_item_service.py` (new) — CRUD + `get_trend(normalized_name, window_days)`. Normalization helper lives here.
- `app/services/fx_service.py` (new) — `get_rate(from_ccy, to_ccy, on_date)` via `exchangerate.host` + Redis cache, key `fx:{from}:{to}:{date}`, 24h TTL (historical rates don't change).
- `app/services/budget/a2a_webhook_service.py` (new) — `enqueue(family_id, transaction_id, payload)`, `dispatch_once(delivery_id)`, `sweep_retries()`. HMAC signing inline.
- `app/services/budget/categorization_rule_service.py` — extend `suggest_category` to accept an `item_name` arg, then iterate per item in the new scanner flow.

`receipt_draft_service.py` unchanged.

## 10. Premium gating

`receipt_scan` is already metered (existing). No change to the count semantics — one scan = one metered unit, regardless of how many items. Additional new feature flags:

- `a2a_webhook` (boolean) — Plus + Pro only. Free tier sees the settings page disabled with an upsell.
- `item_trends` (boolean) — Plus + Pro. Free tier sees items in the confirm card without trend badges.
- `fx_cross_charge` (boolean) — Pro only. When disabled and the matched/fallback account's currency differs from the receipt's currency, the scan routes to the HITL drafts queue with reason `currency_mismatch` rather than picking an arbitrary account. Pro users get the auto-conversion path described in §3 stage (4).
- `iva_breakout` — included for everyone (no gating; it's just a number we already extracted).
- `duplicate_guard` — included for everyone.

## 11. Error handling

| failure | behavior |
|---|---|
| Vision returns no `card_last4` | account = last-used. `account_match.strategy = "last_used"`. Confirm card shows amber dot. |
| `card_last4` matches >1 account | narrow by currency. If still >1, fallback to last-used. |
| FX fetch fails | store transaction in receipt currency, `fx_rate = null`, response includes `warnings: ["fx_unavailable"]`. UI shows soft toast. |
| Webhook delivery fails | row stays `pending` → retried by sweep. Never blocks scan response. |
| Webhook URL invalid on save | `PUT /a2a-webhook` returns 422. |
| Duplicate false positive | `force=true` resolves. UI offers `Save anyway`. |
| IVA not extractable | leave `iva_cents = null`. No guess. UI omits the pill. |
| Vision JSON malformed | as today — `ValidationError("Could not parse receipt data from image")`. |
| Low confidence (< 0.3 or no total) | as today — `BudgetReceiptDraft` HITL queue, none of the 7 stages run. |
| Item count > 200 | reject with `ValidationError` (defensive cap; real receipts top out around 80). |
| LiteLLM proxy rejects (budget exceeded) | as today — `ValidationError`. |

## 12. Testing

Target ~25 new tests in `tests/test_receipt_scanner_v2.py`. Backend:

1. `card_last4` exact match picks the account
2. `card_last4` ambiguous → currency tiebreaker picks correct account
3. `card_last4` ambiguous → still >1 after tiebreak → last-used fallback
4. No `card_last4` → last-used fallback
5. Caller-supplied `account_id` overrides everything
6. Duplicate guard fires on same-payee same-amount within 60 s
7. Duplicate guard does NOT fire across families (tenant isolation)
8. Duplicate guard does NOT fire when amount differs by >1%
9. `force=true` bypasses duplicate guard and commits
10. Items persisted with correct `normalized_name`
11. Normalization strips accents and unit suffixes
12. Trend endpoint computes `pct_change` over 90-day window
13. Trend endpoint returns null when `sample_size < 3`
14. FX cross-charge stores `fx_rate`, `original_amount_cents`, `original_currency`
15. FX failure → graceful skip, no fx_rate, warning emitted
16. IVA extracted and stored
17. Webhook fires on commit when enabled (mock httpx; assert payload + signature)
18. Webhook does NOT fire when disabled
19. Webhook does NOT fire when family has no row
20. Webhook retry sweep picks up `pending` deliveries past `next_retry_at`
21. Webhook signature is HMAC-SHA256 of body with family secret
22. Tenant isolation: family A's `GET /items` cannot return family B's items
23. Low-confidence still routes to drafts queue (regression)
24. Shopping auto-check still runs (regression)
25. `card_last4` migration backfills `**9222`, `***313`, `terminada en 1234` correctly

Frontend (Playwright, in `e2e-tests/`):

26. One-tap happy path: snap → confirm card → save → land on transactions list with new row
27. Duplicate modal flow: re-snap same receipt within 60 s → modal → `Save anyway` → second transaction created
28. FX display: scan USD receipt against MXN account → confirm card shows both totals
29. IVA pill renders when present, hidden when absent
30. Trend badges render when sample_size >= 3, hidden otherwise

## 13. Open questions

None. All previously open questions decided during brainstorm.

## 14. Out of scope / follow-ups

- Live camera coaching ("hold steady, move closer") — deferred.
- Batch upload (drop 10 receipts at once) — deferred.
- Multi-page PDF receipts — still first-page-only.
- Voice memo overlay — deferred.
- Merchant logo lookup pipeline — confirm card uses initials avatar in v2; logo integration is a polish follow-up.
- Inline edit of items post-scan — re-scan flow only in v2.
- Location geocoding into `location_hint` — webhook field is reserved (always null in v1).
- i18n cleanup of W1–W6 inline ternaries — tracked in `project_i18n_debt.md`, separate effort.

## 15. Rollout

Single Alembic migration `wave4_scanner_v2`. No data flag. The new fields are all nullable, so existing transactions continue to work. The `card_last4` backfill on accounts runs in the migration body.

Order of work, suggested:
1. Migration + models + schemas.
2. `FXService`, `transaction_item_service`, `account_matching_service`, `duplicate_guard_service` — pure services, easy to test in isolation.
3. Extend scanner service to call them; wire new vision prompt.
4. Extend `scan-receipt` endpoint; add `409 dup_warning` path.
5. New endpoints (items, trends, webhook config, internal retry).
6. Webhook dispatch + retry scheduler.
7. Premium gating updates.
8. Frontend: confirm card redesign first (biggest visible delta), then items list page, then webhook settings page.
9. Playwright tests.
10. Deploy via `./scripts/deploy-gcp.sh`.

Estimated size: ~12 PRs if split, or one large branch if bundled.
