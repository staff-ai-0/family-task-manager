# Outstanding Chore-Paycheck Weeks — design

Date: 2026-07-21

## Problem (forensic finding)

Two payout systems share the `/parent/payouts` page but only one has a bug:

- **Gig cash** (`User.cash_cents`): an unscoped running balance, payable anytime. Works correctly — this is what the user meant by "did for gigs."
- **Weekly chore paycheck** (`allowance_mode` in `chore_proportional` / `chore_gated` / `points_rate`): computed per calendar week, and the release path is hardcoded to "this week" at every layer:
  - `backend/app/api/routes/bank.py:233` — `release_chore_paycheck` always computes `week_of = _family_local_today(...)`. Not a default: the only value it ever uses.
  - `ChorePaycheckReleaseBody` has only `adjustment_cents` — no `week_of` field exists in the request at all.
  - `BankService.payout_summary` → `chore_paycheck_preview` also defaults to today's week.
  - Both frontend surfaces (`/parent/payouts`, `/parent/settings/family-bank`) label the section "this week" and POST an empty `{}` body to release.
  - `chore_paycheck_history` only lists weeks that *were* released — a skipped week leaves no record.
  - The only signal a week was missed is a one-time, dismissible notification (`_remind_unreleased_paychecks`).

**Net effect:** once a week rolls over unreleased, that week's earned pay becomes unreachable through the app — no error, no persistent visibility, no way to pay it. The underlying task-completion data is intact (`_chore_units` can still compute it), but nothing in the code path ever asks it about a week other than "today's."

The "parent reviews before paying" design itself is intentional (documented in `bank_service.py`'s own comments) and is not being changed — only the inability to ever reach a past week.

## Decision

**Outstanding-weeks queue.** `/parent/payouts` shows every unreleased chore-paycheck week per kid (not just the current one), oldest first, each independently releasable. `/parent/settings/family-bank`'s per-kid widget simplifies to a count + link into the queue rather than duplicating full release UI.

### Backend

- New `BankService.list_outstanding_weeks(db, target_user, family_id, lookback_weeks=8) -> list[dict]`: walks back from the current week_monday for `lookback_weeks` weeks. A week is **outstanding** if no `CashTransaction(type=ALLOWANCE, week_of=that_monday)` exists for the kid yet. Past outstanding weeks are included only if `assigned_units > 0` for that week (nothing to flag if the kid wasn't even in a chore mode yet); the **current** week is always included regardless (existing "this week, in progress" visibility is preserved). Reuses the existing per-mode calculation (`_chore_paycheck_cents` / `_chore_paycheck_gated` / `_points_rate_cents`) and `_chore_week_tasks` for the per-task breakdown — same math as today, just evaluated across multiple weeks instead of one.
- `release_chore_paycheck` route (`bank.py`): `ChorePaycheckReleaseBody` gains an optional `week_of: Optional[date] = None`. Route uses it when provided, falling back to today (unchanged behavior for any existing caller that omits it). Reject a `week_of` whose Monday is in the future (422) — releasing ahead of time makes no sense and `_chore_units` would just read zero/partial data.
- `BankService.payout_summary`: per-kid row now embeds the full `outstanding_weeks` list (via `list_outstanding_weeks`) instead of a single current-week snapshot. `outstanding_paycheck_total_cents`/`outstanding_grand_total_cents` sum every outstanding week's amount across every kid (the pre-existing `paycheck_total_cents`/`grand_total_cents` stay current-week-only, unchanged, for backward compatibility) — the "Total owed" figure on `/parent/payouts` and `/parent/index.astro` becomes honest about backlog, not just this week.
- New endpoint `GET /api/bank/chore-paycheck/{user_id}/outstanding` → `{"weeks": [...]}`, parent-only. Used by `family-bank.astro`'s simplified widget. The existing singular `GET /chore-paycheck/{user_id}` (current-week-only preview) is **left untouched** — it's also consumed by the kid-facing `bank.astro` for the kid's own "progress this week" meter, which must keep working exactly as it does today.

### Frontend

- `parent/payouts.astro`: the "Cheques de tareas · esta semana" section becomes "Cheques de tareas" (drop "this week") and renders one card per outstanding week per kid (oldest first), each with its own amount, task chips, and Release button. A past (non-current) week gets a small warning marker; the current week is visually unmarked, matching the existing look. Release button POSTs `{week_of, adjustment_cents}` for that specific week — the adjustment input (if any) stays per-card, not global.
- `parent/settings/family-bank.astro`: the existing "this week" release card is replaced with a compact summary — count of outstanding weeks + total amount + a link to `/parent/payouts#historial` (or the relevant kid) — no duplicate release button here. Kid-facing config (allowance mode, cap, etc.) on this page is untouched.

## Out of scope

- No change to the notification/reminder system (`_remind_unreleased_paychecks`) — it still fires; it's just no longer the only way to eventually reach a missed week.
- No change to `flat` mode (auto-paid by the sweep, never had this problem) or to the gig-cash payout flow.
- No change to the kid-facing current-week meter (`bank.astro`, the untouched singular preview endpoint).
- `lookback_weeks=8` is a fixed cap (matches `chore_paycheck_history`'s existing `limit=12` convention) — not user-configurable.

## Testing

Real pytest coverage (this touches money-moving backend logic):
- `list_outstanding_weeks` returns a past unreleased week (assigned>0) and excludes an already-released one (has a matching `CashTransaction`) and excludes a past week with nothing assigned.
- `release_chore_paycheck` route accepts an explicit past `week_of` and correctly credits/marks that week — a regression lock that this doesn't silently pay the current week instead.
- Route rejects a future `week_of` (422).
- `payout_summary`'s `paycheck_total_cents` sums across multiple outstanding weeks for a kid with a multi-week backlog.

Frontend: manual browser verification (per this project's CLAUDE.md UI-change rule) — no new automated test.
