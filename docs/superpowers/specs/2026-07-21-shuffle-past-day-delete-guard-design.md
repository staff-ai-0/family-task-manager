# Shuffle: explicit past-day delete guard

Date: 2026-07-21

## Problem

`TaskAssignmentService.shuffle_tasks_detailed` already never *creates* new rows for days before `today`, and never re-materializes a row that survived as non-`PENDING` (completed/overdue/cancelled). But the delete step that clears old `PENDING` rows before regenerating the week only filters on `family_id` / `week_of` / `status` — it has no date condition. In practice a past day's leftover `PENDING` row is protected because a separate hourly sweep (`mark_overdue_all`) flips it to `OVERDUE` shortly after the day ends, and `OVERDUE` rows are outside the delete's `status == PENDING` filter. But that sweep runs once an hour, not instantly at midnight: a re-shuffle inside that window, before the sweep has run, would delete a still-`PENDING` past-day row and (per the "never creates rows for already-past days" rule) not recreate it — the chore just vanishes instead of surfacing as overdue.

## Decision

Add `TaskAssignment.assigned_date >= today` to the delete_stmt's `and_(...)` in `shuffle_tasks_detailed` (`backend/app/services/task_assignment_service.py:900-907`). `today` is already a parameter of this function (family-local, resolved earlier in the same call). `< today` = "past" is the same convention already used by `check_overdue_assignments`/`mark_overdue_all` in this same file — not a new rule, just applied one place earlier. This makes past-day protection independent of the overdue-sweep's timing.

## Testing

New regression test in `backend/tests/test_task_scheduling_enhancements.py`, alongside the existing closely-related `test_auto_weekly_slot_never_lands_on_past_day`: seed a raw `PENDING` `TaskAssignment` row on Monday directly via the existing `_direct_assignment` test helper (bypassing the shuffle and the overdue-sweep, so it's `PENDING` on purpose — reproducing the exact gap), then call `shuffle_tasks_detailed`/`shuffle_tasks` with `today=` a later day in the same week, and assert the seeded row still exists with `status == PENDING` afterward (not deleted, not flipped, not duplicated).

## Out of scope

- No change to the overdue-sweep itself, its cron interval, or `mark_overdue_all`.
- No frontend change, no migration.
