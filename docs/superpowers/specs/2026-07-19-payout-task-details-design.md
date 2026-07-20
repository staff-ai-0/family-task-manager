# Payouts — Per-Task Detail List on Chore-Paycheck Rows

**Date**: 2026-07-19 · **Status**: approved (user, in-session)

## Problem

The chore-paycheck rows on `/parent/payouts` show only the aggregate
(`120/130 pts · 92%`). The parent can't see *which* tasks produced that number
— what was completed, what's still pending review, what was missed — without
leaving the page.

## Decision

Extend the existing summary endpoint; render a chip list per paycheck row with
a hover/tap tooltip per task. User chose "all week's tasks" over
completed-only so the list explains the whole fraction.

### Backend — extend `GET /api/bank/payout-summary`

Each `PayoutSummaryKid` on a parent-released allowance mode gains
`tasks: list[PayoutTaskDetail]` (empty for `flat`):

```json
{
  "title": "Tender la cama",
  "points": 10,
  "earned_points": 5,
  "status": "credited",
  "grade": "partial",
  "partial_credit_pct": 50,
  "assigned_date": "2026-07-14",
  "completed_at": "2026-07-14T18:02:11Z",
  "approval_notes": "Faltó la almohada"
}
```

- New `BankService._chore_week_tasks(db, family_id, user_id, week_monday)`
  beside `_chore_units`, **same filters** (non-gig `is_bonus=False`,
  non-cancelled, `week_of = week_monday`), joined to `TaskTemplate` for
  title/points, ordered by `assigned_date, title`.
- `status` buckets mirror `_chore_units` credit math exactly:
  - `credited` — COMPLETED + approval NONE/APPROVED; `earned_points` =
    `round(points × pct / 100)` (`pct` = `partial_credit_pct` when grade is
    `partial`, else 100) — same display rounding as `done_points`.
  - `pending_review` — COMPLETED + approval PENDING; earns 0.
  - `missed` — COMPLETED + approval REJECTED (grade `missed`); earns 0.
  - `not_done` — any other non-cancelled status (PENDING/…); earns 0.
- Wired into `BankService.payout_summary` only (teen meter preview unchanged).
- Schema `PayoutTaskDetail` in `app/schemas/bank.py`.

### Frontend — `/parent/payouts` paycheck rows

- Chip row under the `done/assigned pts` line: one chip per task,
  label = title + earned/full pts, color by status (mint = credited,
  amber = pending_review, red = missed, gray = not_done).
- Chip is a `<button>`; detail panel shows on **hover** (desktop) and
  **tap/focus** (mobile — hover doesn't exist on touch). CSS-only:
  `hidden group-hover:block group-focus:block`, panel absolutely positioned
  against the row (row is `relative`) so it spans the row width and never
  clips at card edges.
- Panel content: status word, pts earned vs full (+ partial % when graded
  partial), day, parent notes when present. ES/EN inline ternaries
  (existing page pattern).

## Wording

These are chores → "tarea/task" everywhere; "gig" stays reserved for the cash
board (per review-queue wording rule).

## Testing

- Backend pytest (`test_payout_summary.py`): tasks array present with correct
  status/earned per bucket (full, partial, pending-review, missed, not-done);
  gig + cancelled + other-week exclusion; flat mode → empty list; fixed
  `week_of` dates (Sunday trap).
- `astro check` + build for frontend; no e2e in scope.

## Out of scope

- Gig-cash cards keep no task list (gigs pay per-claim, different surface).
- Teen meter endpoint (`GET /api/bank/chore-paycheck/{user_id}`) unchanged.
