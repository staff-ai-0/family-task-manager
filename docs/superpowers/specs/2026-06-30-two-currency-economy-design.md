# Two-Currency Economy: Points (privileges) vs Cash (gigs)

**Date:** 2026-06-30
**Status:** Approved (design) — pending spec review → implementation plan
**Branch:** `feat/two-currency-economy`

## Problem

The product economy has two distinct currencies, but the code has one:

- **Mandatory chores** (sweep, mop, dishes) should earn **points** — a *privilege*
  currency spent on screen time, movie pick, what's for dinner, BBQ day, etc.
  **Not money.**
- **Gigs** (bonus tasks) should earn **cash** ($MXN) — real allowance money.

### Current reality (what the code does today)

- A single `User.points` balance. `PointTransaction` is its ledger.
- **Gigs** credit `user.points` via `PointsService.award_gig_points`
  (`_award_assignment`). The gig board treats `1 pt = $1 MXN`, so points and cash
  are conflated in one number.
- **Mandatory chores** credit **nothing** on completion
  (`task_assignment_service.complete_assignment`, mandatory path: "completes
  silently, awards no points").
- A `TaskTemplateCreate`/`Update` validator (`_enforce_mandatory_zero_points`)
  *forbids* non-bonus tasks from having `points != 0`. The redesigned
  `TaskCreateModal` always sends `points >= 1`, so **every mandatory-task
  creation 422s** — this is the production "error when creating a task" bug.
- A legacy `/api/points-conversion/` route converts points → money through
  `finance-api:5007`, the **decommissioned** Actual Budget service (Phase 10).
  Dead, and conceptually wrong under the new model (points must never become cash).

### Goal

Separate the two currencies cleanly:

| Action | Currency | When |
|--------|----------|------|
| Complete mandatory chore | **+ points** (privilege) | immediately, no approval |
| Gig approved | **+ cash** ($MXN) | on parent/auto approval |
| Redeem reward | **− points** | on redemption (unchanged) |
| Parent pays kid | **− cash** | parent records a payout |

Points never convert to cash. Cash never buys rewards.

## Non-Goals

- No reward purchasable with cash (rewards stay points-only).
- No external/budget integration for kid cash (kept independent of the parent
  household budget system).
- No automatic payout / bank transfer. Payout is a manual parent action.
- No reclassification of historical `user.points` (post-reset balances ≈ 0;
  count is confirmed before any prod migration).

## Design

### §1 — Data model

- **`User.cash_cents`** — `Integer`, `default=0`, `not null`. Pending-payout cash
  balance, in centavos.
- **`cash_transactions`** table — mirror of `point_transactions`:
  - `id` (UUID PK)
  - `user_id` (FK users, not null, indexed)
  - `family_id` (FK families, not null, indexed) — multi-tenant invariant
  - `type` (`CashTransactionType`)
  - `amount_cents` (Integer; may be negative for payouts / clawbacks)
  - `balance_before` (Integer)
  - `balance_after` (Integer)
  - `gig_claim_id` (FK gig_claims, nullable, `ON DELETE SET NULL`)
  - `created_by` (FK users, nullable — the parent who recorded a payout)
  - `description` (String)
  - `created_at` (DateTime tz)
- **`CashTransactionType`** enum (str): `GIG_EARNED`, `PAYOUT`, `ADJUSTMENT`.
- `User.points` keeps its current meaning = **privilege points**.

### §2 — Earning rules

**Mandatory chore (`is_bonus=False`)**
- `complete_assignment` mandatory path: after marking COMPLETED, award
  `template.effective_points` (base × effort multiplier 1.0/1.5/2.0) to
  `user.points` via `PointsService.award_points_for_task`
  (`TransactionType.TASK_COMPLETED`). Immediate, no approval.
- `effective_points` is used (not base) to match what the task cards already
  display.

**Gig (`is_bonus=True`)**
- Approval path (`_award_assignment` and the collaboration re-split) credits
  **cash** instead of points: `award_points_per_completer * 100` centavos via
  `CashService.award_gig_cash` (`CashTransactionType.GIG_EARNED`).
- Must support **negative** amounts for the collaboration re-split clawback
  (mirror of `award_gig_points`'s negative-points behavior).
- Gig path no longer writes a `PointTransaction`.

**Validator removal**
- Delete `_enforce_mandatory_zero_points` from `TaskTemplateCreate` and
  `TaskTemplateUpdate`. With it gone, the existing frontend payload
  (`is_bonus=false, points>=1`) validates — the 422 is fixed. The `points`
  field now means "the value": privilege points for a chore, peso value for a gig.

### §3 — Payout flow

- Parent-only `CashService.record_payout(db, user_id, family_id, amount_cents,
  created_by)`:
  - Validates `0 < amount_cents <= user.cash_cents` (no overdraw).
  - Writes a `PAYOUT` txn with `amount_cents = -amount`, debits `cash_cents`.
- `CashService.adjust(...)` (parent manual `ADJUSTMENT`, signed) — optional,
  symmetric with `PointsService.create_parent_adjustment`.

### §4 — API surface

New `CashService` (`backend/app/services/cash_service.py`):
- `get_balance(db, user_id) -> int`
- `award_gig_cash(db, user_id, family_id, gig_claim_id, amount_cents, description=None)` — caller commits (mirrors `award_gig_points`)
- `record_payout(db, user_id, family_id, amount_cents, created_by) -> CashTransaction`
- `adjust(db, user_id, family_id, amount_cents, reason, created_by) -> CashTransaction`
- `get_history(db, user_id, limit=50) -> list[CashTransaction]`
- `get_summary(db, user_id) -> dict` (balance, total_earned, total_paid)

New routes `/api/cash/` (`backend/app/api/routes/cash.py`):
- `GET /api/cash/balance` — current user's cash summary (TEEN/CHILD).
- `GET /api/cash/history` — current user's cash ledger.
- `GET /api/cash/family` — parent: every kid's cash summary (earned/paid/pending).
- `POST /api/cash/{user_id}/payout` — parent: record a payout (full/partial).
- `POST /api/cash/{user_id}/adjust` — parent: manual adjustment (optional).

Changed:
- `_award_assignment` / `_settle_collaboration` → `CashService.award_gig_cash`.
- Gig notifications/push: "+$N MXN" instead of "+N pts".

### §5 — Frontend

- **Kid dashboard:** two balances — ⭐ Puntos (privileges) and 💵 Cash (pending
  payout, `$X.XX MXN`).
- **Reward store:** cost in **points** (unchanged).
- **Gig board:** show **$** (cash) for gig value/earnings.
- **Task cards:** chore → "+N pts"; gig → "$N".
- **Parent:** per-kid screen with cash balance + "Pagar" (full/partial) + payout
  history. New page under `/parent/`.
- Remove any frontend usage of `/api/points-conversion/` (the kid "convert to
  money" UI).

### §6 — Cleanup, migration, units

- **Remove** `/api/points-conversion/` route, its router registration, schema,
  and frontend references entirely.
- **Units:** cash stored as centavos (Integer). Gig points→cents = `× 100`.
  Display `$X.XX MXN`.
- **Migration (Alembic):**
  - `up`: add `users.cash_cents` (default 0, not null); create `cash_transactions`
    + `cashtransactiontype` enum.
  - `down`: drop table + enum + column.
  - No data backfill; `user.points` untouched. Confirm `max(user.points)` and
    transaction counts on prod before migrating (expected ≈0 post 2026-06-23 reset).

### §7 — Testing

- `CashService`: award (positive), payout full, payout partial, overdraw rejected,
  negative re-split clawback, adjustment signed, balance/summary math.
- `complete_assignment`: mandatory completion credits `effective_points` to
  `user.points` and writes a `TASK_COMPLETED` row; does **not** touch cash.
- Gig approval: credits `cash_cents` (`= pts*100`) and a `GIG_EARNED` row; writes
  **no** `PointTransaction`.
- Collaboration re-split: cash math matches old points math (pot / completers),
  clawback works.
- Validator removed: `TaskTemplateCreate(is_bonus=False, points=10)` is valid.
- Routes: `/api/cash/*` auth (parent vs kid), payout no-overdraw 4xx.
- Migration up/down runs clean.

## Out-of-scope follow-ups (note, don't build now)

- Jarvis/MCP cash-aware tools (read cash balances, record payouts via Jarvis).
- Cash → savings split / allowance scheduling.

## Related (separate, already done on this branch)

- **Jarvis Gemini schema fix** — `mcp/openai_bridge.py` `_gemini_safe` sanitizer.
  Independent of this economy work; verified live against the prod Gemini proxy.
  Fixes "jarvis not working" (Gemini 400 on malformed array `items`).
