# Teen chore-paycheck meter redesign — design spec

Date: 2026-07-21
Status: approved (pending user review of this doc)

## Problem

`chore_proportional`/`chore_gated` weekly pay is computed **live**: `assigned_units`
(the denominator) is a real-time sum over every non-cancelled `TaskAssignment` row
for that `week_of`, joined against each `TaskTemplate`'s *current* `points`. Two
triggers retroactively change an in-progress week's numbers:

1. A new task template added mid-week generates assignments for the remaining
   days (existing mid-week auto-distribute behavior, PR #146) — `assigned_units`
   jumps immediately, diluting the already-earned share of days already worked.
2. Editing an existing template's `points` mid-week changes the contribution of
   already-completed assignments retroactively (nothing snapshots the value at
   completion time).

The teen-facing "Mi pago por tareas" meter (`frontend/src/pages/bank.astro`,
lines 108–129) surfaces exactly the numbers that move when this happens: a live
projected dollar figure (`$183.33 / $250.00`) and a raw points fraction
(`16/90 pts hechos`). A parent adding or editing a task mid-week visibly moves
these numbers for the teen with no explanation, which reads as "money being
taken away" — the real-world incident this design is preventing (two teens
already affected by an unrelated but similarly-shaped payout confusion this
session, see `docs/superpowers/specs/2026-07-21-outstanding-chore-paychecks-design.md`).

Two fixes were considered for the underlying live-recompute behavior (freezing
`assigned_units`/`points` to their Monday-start values via a new
`payout_points` column + template-creation-date cutoff). **Rejected**: the
family's owner decided the backend recompute is fine to leave as-is — the
actual fix is to stop showing teens the numbers that move, while keeping full
transparency for parents.

## Decision

1. **Parent-facing views are unchanged.** `frontend/src/pages/parent/payouts.astro`,
   `frontend/src/pages/parent/settings/family-bank.astro`, and every backend
   payout calculation (`bank_service.py` — `_chore_units`, `_paycheck_projection`,
   `_chore_paycheck_cents`, `_chore_paycheck_gated`, `list_outstanding_weeks`)
   stay exactly as they are today. Parents keep full per-task dollar/point
   visibility and the ability to release pay — that visibility is the tool
   they need to audit and explain any change themselves.

2. **Teen-facing view (`bank.astro`) drops all moving numbers.** The current
   meter shows `projected_cents`, `cap_cents`, `pct`, `done_points`,
   `assigned_points` — all of which shift with the live recompute. Replace
   with:
   - The **weekly goal itself stays visible** (`cap_cents`, e.g. "$250.00") —
     it's parent-set and static within a week, not a live projection.
   - A **static explanatory line**: "Tu pago depende de qué tan bien y cuánto
     completes tus tareas de esta semana" (EN: "Your pay depends on how well
     and how much of your tasks you complete this week") — no numbers.
   - A **three-segment colored progress bar** replacing the single mint fill:
     - **Green** — the existing `pct` (done/assigned), unchanged computation,
       just no longer printed as a number next to it.
     - **Red** — a new `discounted_pct`: the share of assigned points that a
       *parent has already graded* as fully missed (`approval_status ==
       REJECTED`) or partially incomplete (`approval_status == APPROVED` with
       `completion_grade == 'partial'`). This only turns red on an explicit
       parent grading decision — never as a side effect of a new task being
       added (an ungraded/not-yet-due task is neutral, not red).
     - **Gray/neutral** — everything else: not yet done but still has time
       this week, or completed and awaiting parent review. `100 - pct -
       discounted_pct`.
   - No numbers are rendered on or near the bar. It's a pure visual proportion
     signal, matching "they just need to know their pay is proportional to
     quality and amount of completion."
   - The **"¡Pago liberado! $X 🎉" reveal is unchanged** — once a week is
     actually released the amount is a settled fact, not a moving projection,
     so it's fine (and useful) for the teen to see the real number then.

3. **One new backend field**, no schema migration, no new endpoint:
   `ChorePaycheckPreview.discounted_pct: int` (0–100), computed in
   `BankService._paycheck_projection` (or a small addition to `_chore_units`)
   from the same per-row data already fetched (template points, status,
   approval_status, completion_grade, partial_credit_pct) — no new query.
   Formula, using the existing `×100`-scaled unit convention:
   ```
   lost_units = Σ over rows where status == COMPLETED and approval_status in (APPROVED, REJECTED):
       REJECTED            → pts * 100                      (full loss)
       APPROVED + partial  → pts * (100 - partial_credit_pct) (partial loss)
       APPROVED + full     → 0                                (no loss)
   discounted_pct = round(100 * lost_units / assigned_units) if assigned_units > 0 else 0
   ```
   `pct` (existing field, = `done_units/assigned_units`) is untouched. Note
   `pct + discounted_pct <= 100` always holds at the unit level since
   `lost_units` and `done_units` are drawn from disjoint rows; independent
   `round()` of the two ratios can theoretically overshoot by a rounding
   point in a rare edge case, so the frontend must clamp the gray segment to
   `max(0, 100 - pct - discounted_pct)` rather than assume it's always exact.

4. **Scope note**: an assignment that goes `OVERDUE` (day passed, kid never
   completed it, no parent review happened) stays in the neutral/gray bucket,
   not red — red is specifically reserved for an explicit parent grading
   decision, per "if a task is qualified BY THEIR PARENT as incomplete." If
   the family wants overdue-with-no-review to also read as red, that's a
   follow-up decision, not part of this change.

## Non-goals

- No change to any payout math, cap, gate, or release logic.
- No change to parent-facing screens.
- No new database column or migration.
- No change to `points_rate`/`flat` modes (already immune to the live-recompute
  concern; this design doesn't touch them either).

## Testing

- Backend: unit tests for the new `discounted_pct` computation —
  all-green week (0%), a REJECTED task (full loss reflected), a partial-grade
  task (partial loss reflected), a mix, and the invariant `pct +
  discounted_pct <= 100`. Also: a NOT_DONE (not yet due) or PENDING
  (awaiting review) task must contribute 0 to `discounted_pct` regardless of
  when it was added.
- Frontend: `npm run check` + manual verification that the three segments
  render with the right proportions and that no `$`/point numbers appear in
  the teen meter (only the static cap amount and the released-amount reveal).

## Files touched

| File | Change |
|------|--------|
| `backend/app/schemas/bank.py` | Add `discounted_pct: int` to `ChorePaycheckPreview` |
| `backend/app/services/bank_service.py` | Compute `lost_units`/`discounted_pct` alongside the existing `_chore_units`/`_paycheck_projection` math |
| `backend/tests/test_chore_paycheck.py` (or new test file) | New tests per Testing section above |
| `frontend/src/pages/bank.astro` | Replace the live meter (lines 108–129) with the static-goal + explanatory line + three-segment bar; keep the released-amount reveal |
