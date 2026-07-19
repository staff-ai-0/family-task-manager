# Economy v2: task grading, configurable payment model, module registry

**Date**: 2026-07-19 · **Status**: approved (user, 2026-07-19) · **Branch**: `feat/economy-grading-modules`

## Context

Two user asks, validated against the 2026-07-07 competitor intel (`docs/audit/2026-07-07/02-competitor-intel.md`):

1. **Scope segregation** — budget, tasks, meals, shopping feel like separate apps. Competitor evidence says the bundle is the moat (OurHome/Cozi/Maple/FamilyWall retention data) but clutter is the top complaint category. Decision: keep everything, add per-family module toggles + integration story. No competitor offers module customization — whitespace.
2. **Configurable payment model** — families choose between a points piece-rate (e.g. 10 pts = 10 MXN) and a fixed weekly amount distributed across tasks by weight, with graded completion (complete / almost / missed / comments).

Most of the payment infra already exists in Family Bank (`kid_bank.py`, `bank_service.py`): allowance modes `flat` / `chore_proportional` / `chore_gated`, payday weekday sweep, Spend/Save/Share splits, parent interest + match. This design extends it rather than building a parallel engine.

## Approved decisions

- Scope: **module toggles + integration** (all modules stay; per-family on/off; onboarding starter profiles).
- Payout math: **add `chore_weighted` as a 4th mode** — existing `chore_proportional` (count-based) untouched.
- Partial credit: **parent slider at review, default 50%**.
- Points→cash: **weekly payday via Family Bank**; converted points are **deducted** (points are pending cash in `points_rate` mode, not a double currency).

## Phase 1 — Task grading

**Schema** (`task_assignments`, additive migration):

- `completion_grade`: enum `full` | `partial` | `missed`, nullable (NULL = graded pre-feature or ungraded).
- `partial_credit_pct`: smallint nullable, 0–100; only meaningful when grade = `partial`.

**Behavior**:

- Parent review flow becomes 3-way: **Complete** (100%) · **Almost** (slider 25/50/75, default 50) · **Missed** (0%). Any grade may carry a comment — reuses the existing `approval_notes` column, now surfaced to the kid.
- Points credited = `round(effective_points × pct / 100)` (grade pct; existing effort multiplier still applies inside `effective_points`).
- `full` maps to approval `APPROVED`; `partial` also `APPROVED` (with reduced credit); `missed` maps to `REJECTED` semantics (trust-streak reset, no celebration) while recording the grade for payout math.
- Optional auto-consequence on `missed` behind a per-family flag, default **off** (uses existing consequences module).
- Kid surface: task detail + notification show grade + parent comment. Overdue sweep unchanged — grading happens only at parent review.

## Phase 2 — Configurable economy

**Schema** (additive):

- `families.point_value_cents`: int, default 100, CHECK > 0. 100 = 1 pt = $1 MXN (matches the gig-board anchor). Family-configurable in Family Bank settings.
- `kid_bank_accounts.allowance_mode` grows to 5 values: `flat`, `chore_proportional`, `chore_gated` (untouched), plus:
  - **`chore_weighted`** — payout = `allowance_cents × Σ(points_i × pct_i) / Σ(points_i over all assigned)` for the week. Fixed weekly pot distributed by task weight; grade pct scales each task's share.
  - **`points_rate`** — payout = `Σ(credited points that week) × point_value_cents`. Piece-rate; no `allowance_cents` cap involved. At payday the converted points are **deducted** from the kid's points balance (they were pending cash). Deduction is recorded as a point transaction with a dedicated reason so history stays auditable.
- Per-kid mode selection is unchanged in shape — a 6-year-old can stay on stars/points while a teen runs a weighted budget.

**Reuse**: payday sweep, chore-paycheck preview endpoint, idempotency via `last_chore_paycheck_week`, jar splits, interest, match — all as-is. New modes slot into `_chore_paycheck_*` dispatch and the sweep's mode filter.

**Rounding**: all money math in integer cents; remainders follow the existing `distribute_points` floor pattern (no silently lost cents).

## Phase 3 — Module registry

**Schema**: `families.enabled_modules` JSONB nullable (NULL = all on, the pre-feature default — zero behavior change for existing families).

- Togglable: `meals`, `shopping`, `calendar`, `pet`, `chat` (chat+dm), `budget`, `gigs` (gigs+bank+cash).
- Always-on core: tasks, rewards, consequences, points, members, settings.

**Behavior**:

- Parent settings page: toggle list.
- `BottomNav` + `MoreSheet` render only enabled modules; disabled slots fall back per a priority order.
- Disabled deep links redirect to dashboard with a "module off" notice (Astro middleware check on page routes). Backend API routes stay live — same-family data, no security boundary; frontend-only gating keeps it cheap.
- Onboarding: new families pick a starter — **Chores & allowance** (side modules off) · **Family OS completo** (all on) · custom checklist.
- Meals→shopping→budget loop stays and is the marketed integration story; no new engine this phase.

## Testing

- Phase 1: grading math (rounding, 0/25/50/75/100), missed → streak reset + no celebration, notes surfaced, ungraded legacy paths.
- Phase 2: payday formulas for both new modes — zero-assigned week, all-missed week, rounding, grade multipliers, points deduction ledger entry, idempotent re-release, existing 3 modes regression.
- Phase 3: nav render gating per role, redirect middleware, NULL = all-on default, onboarding seeding.
- Migrations additive, nullable/server-defaulted → CI upgrade/downgrade round-trip safe.

## Out of scope

- Backend enforcement of module toggles (frontend-only this pass).
- Deeper shopping→budget automation (future phase).
- Any change to gig-board pricing (cash-priced offerings unchanged).
- i18n refactor — new UI strings follow the existing inline ES/EN ternary pattern.
