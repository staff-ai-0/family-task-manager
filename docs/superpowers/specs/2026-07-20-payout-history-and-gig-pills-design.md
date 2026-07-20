# Payouts — Weekly History + Gig Cash Pills

**Date**: 2026-07-20 · **Status**: approved (user, in-session) · One PR.

## Problem

`/parent/payouts` shows only the CURRENT week's chore paycheck and the
CURRENT gig-cash balance. Two gaps:

1. No history: once a chore paycheck is released, the parent can't see past
   weeks — how much, when, or which tasks earned it.
2. Gig cash is a faceless lump sum ("$120 pending") — no visibility into
   which gigs make up that number.

## Decision

### A. Weekly chore-paycheck history

**New column**: `cash_transactions.week_of` (DATE, nullable). Populated going
forward at release time; historical rows stay NULL — history starts from
when this ships, no backfill attempted (old rows have no reliable
machine-parseable week, only a human-readable Spanish description string).

- `CashService.credit_split_rows` gains an optional `week_of: date | None`
  kwarg, threaded onto each created row.
- `BankService.release_chore_paycheck` passes `week_of=week_monday` at its
  existing `credit_split_rows(..., CashTransactionType.ALLOWANCE, ...)` call.
- Migration: additive nullable column, no backfill, no data loss risk.

**New endpoint** `GET /api/bank/chore-paycheck/{user_id}/history` (parent
only, same tenant/role checks as the existing chore-paycheck routes):

```json
{
  "weeks": [
    {
      "week_of": "2026-07-14",
      "amount_cents": 25000,
      "released_at": "2026-07-20T13:00:00Z",
      "tasks": [ /* same PayoutTaskDetail shape as payout-summary */ ]
    }
  ],
  "has_more": false
}
```

- Query: `cash_transactions` where `user_id=target`, `type=ALLOWANCE`,
  `week_of IS NOT NULL`, grouped back to one row per `week_of` (sum
  `amount_cents` across the jar-split rows), ordered newest first, capped at
  **12 weeks** (`has_more=true` if more exist — no silent truncation).
- Per week, `tasks` reuses `BankService._chore_week_tasks(db, family_id,
  user_id, week_of)` — same function PR #139 built, just called with a past
  `week_of` instead of the current one. Same status buckets, same shape.
- Schema: `PayoutWeekHistory` (week_of, amount_cents, released_at, tasks) +
  `PayoutHistoryResponse` (weeks, has_more) in `app/schemas/bank.py`.

**Frontend**: on each paycheck row in `/parent/payouts`, a "Ver historial /
View history" link/toggle. Expands to a list of past weeks (amount + date),
each week itself expandable to the same task-chip row PR #139 already
renders — same component pattern, same colors, same hover/tap tooltip.
Fetched lazily (own endpoint, not bundled into `payout-summary`) since it's
not needed on first paint and can grow.

### B. Gig cash pills

**New endpoint field**: extend `GET /api/cash/family` (`CashSummary`) with
`recent_gigs: list[GigCashPill]` per kid:

```json
{
  "title": "Lavar el carro",
  "amount_cents": 5000,
  "approved_at": "2026-07-18T10:00:00Z",
  "approval_notes": "Buen trabajo"
}
```

- Query per kid: find the most recent `cash_transactions` row with
  `type=PAYOUT` (if any) → its `created_at` is the cutoff. Select all
  `type=GIG_EARNED` rows for that kid with `created_at > cutoff` (or all-time
  if no payout yet), join `gig_claim_id → GigClaim → GigOffering.title`,
  pull `GigClaim.approved_at` / `approval_notes`. Rows with no
  `gig_claim_id` (shouldn't happen for GIG_EARNED, but defensive) are
  skipped rather than shown with a blank title.
- **Caveat, stated in the UI, not just code comments**: payouts are lump-sum
  debits, not tied to specific gigs — "since last payout" is the best
  available signal for "still pending," not a guarantee. Section label:
  "Gigs since last payout" (ES: "Gigs desde el último pago"), not "unpaid
  gigs," so the copy doesn't overclaim.
- Schema: `GigCashPill` (title, amount_cents, approved_at, approval_notes)
  added to `CashSummary` in `app/schemas/cash.py`.

**Frontend**: pills under each gig-cash kid card on `/parent/payouts`
(mirrors the chore-paycheck chip styling — one color, since these are all
"earned, counted" by construction, no status buckets needed here). Hover/tap
→ amount, approved date, approval notes. Reuses the same CSS tooltip pattern
(group-hover/group-focus, positioned above to clear BottomNav).

## Wording

"Gig" stays reserved for gig-board cash (per existing rule) — correct here,
this section IS the gig board's money. Chore-paycheck history uses
"tarea/task" per the same rule.

## Testing

- Backend: migration round-trip (upgrade/downgrade). `credit_split_rows`
  writes `week_of` when passed. History endpoint: multiple past weeks
  aggregate correctly across jar-split rows, `has_more` at >12 weeks, parent-
  only 403, multi-tenant isolation, empty when kid has never been released.
  Gig pills: cutoff-at-last-payout logic (no payout yet = all-time; a payout
  in between = only later gigs show), title join, tenant isolation.
- Frontend: `astro check` + build. Driven live (Playwright) same as PR #139:
  expand history, hover/tap a past week's chips, hover/tap a gig pill,
  mobile viewport.

## Out of scope

- No backfill of `week_of` for pre-existing ALLOWANCE rows.
- No per-gig "paid" flag / FIFO payout-to-gig matching — explicitly
  approximated via the last-payout cutoff, documented as such in the UI.
- Kid-facing pages unchanged.
