# Payout Summary Dashboard — Design

**Date**: 2026-07-19 · **Status**: approved (user, in-session)

## Problem

Parents have no single view of "how much do I owe the kids right now". Gig cash
pending lives in `/parent/payouts` (buried under More → Payouts); weekly chore
paychecks to release live in `/parent/settings/family-bank`. Nothing aggregates
a total, and the parent home page surfaces neither.

## Decision

One aggregate endpoint + two frontend surfaces:

### Backend — `GET /api/bank/payout-summary` (parent-only)

```json
{
  "kids": [
    {
      "user_id": "…", "name": "Ariana",
      "cash_pending_cents": 12000,
      "paycheck_cents": 0,
      "paycheck_released": false,
      "allowance_mode": "flat"
    }
  ],
  "cash_total_cents": 17000,
  "paycheck_total_cents": 0,
  "grand_total_cents": 17000
}
```

- `cash_pending_cents` = kid's `cash_cents` (gig-board balance awaiting payout).
- `paycheck_cents` = this week's projected chore paycheck, **only** for
  parent-released allowance modes (`chore_proportional`, `chore_gated`,
  `points_rate`), computed via the existing
  `BankService.chore_paycheck_preview`; `0` when already released this week
  (`paycheck_released: true`) or mode is `flat`.
- New `BankService.payout_summary(db, family_id)`; route in
  `app/api/routes/bank.py`; schema in `app/schemas/bank.py`.
- Kids = family users with role CHILD/TEEN (same rule as `/api/cash/family`).

### Frontend — parent home (`/parent`)

Card above the shortcuts grid, rendered only when `grand_total_cents > 0`:

> 💵 Por pagar a los kids: **$170.00** — Gigs $170.00 · Cheques $0.00 →

- Links to `/parent/payouts` when the `gigs` module is on; otherwise (cash is
  necessarily 0) links to `/parent/settings/family-bank`.

### Frontend — `/parent/payouts`

- Header block: grand total + Gigs/Cheques breakdown (from the same endpoint).
- New section "Cheques de la semana": one row per kid on a parent-released
  mode — projected amount, pts done/assigned, and a **Liberar** button posting
  to the existing `POST /api/bank/chore-paycheck/{user_id}/release` (same
  pattern as family-bank.astro). Released → shows "Liberado ✓".
- Existing gig-cash cards unchanged.

## Wording

Review-queue rule holds: "gig" only for the cash board section; the weekly
paycheck is "cheque de tareas / chore paycheck". ES/EN inline ternaries
(existing pattern).

## Testing

- Backend pytest: totals across kids; each allowance mode contributes (or not);
  released week → 0 + flag; multi-tenant isolation; parent-only 403.
- `astro check` for frontend; no e2e in scope.

## Out of scope

- No scheduler/auto-pay changes; `payout_cadence` stays advisory.
- No changes to kid-facing pages.
