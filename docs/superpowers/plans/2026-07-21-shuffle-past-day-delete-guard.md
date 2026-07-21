# Shuffle Past-Day Delete Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a same-week task re-shuffle never delete a `PENDING` assignment on a day that's already past, independent of whether the hourly overdue-sweep has run yet.

**Architecture:** One additional condition on an existing delete query in `TaskAssignmentService.shuffle_tasks_detailed`, using the `today` value the function already computes/receives. One new regression test that reproduces the gap directly (seeds a stale `PENDING` row via the existing `_direct_assignment` test helper, bypassing the sweep) rather than relying on timing.

**Tech Stack:** FastAPI + SQLAlchemy (backend service), pytest.

## Global Constraints

- `< today` means "past day"; this is the existing convention in `check_overdue_assignments`/`mark_overdue_all` in the same file — reuse it, don't invent a new comparison direction.
- No change to the overdue-sweep, its interval, or any frontend/migration.
- Spec: `docs/superpowers/specs/2026-07-21-shuffle-past-day-delete-guard-design.md`

---

### Task 1: Add the delete-guard + regression test

**Files:**
- Modify: `backend/app/services/task_assignment_service.py:900-907` (`shuffle_tasks_detailed`'s `delete_stmt`)
- Modify: `backend/tests/test_task_scheduling_enhancements.py` (add import + new test)

**Interfaces:**
- Consumes: `today` — already a local variable in `shuffle_tasks_detailed`, resolved at the top of the function (family-local date, either passed in or computed via `_family_local_today`). No signature change.
- Produces: nothing new consumed elsewhere — this only tightens an existing delete's WHERE clause.

- [ ] **Step 1: Add the date condition to the delete statement**

In `backend/app/services/task_assignment_service.py`, `shuffle_tasks_detailed` currently has (lines 900-907):

```python
        delete_stmt = sql_delete(TaskAssignment).where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.week_of == week_monday,
                TaskAssignment.status == AssignmentStatus.PENDING,
                TaskAssignment.template_id.not_in(interval_template_ids),
            )
        )
```

Replace with:

```python
        delete_stmt = sql_delete(TaskAssignment).where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.week_of == week_monday,
                TaskAssignment.status == AssignmentStatus.PENDING,
                TaskAssignment.template_id.not_in(interval_template_ids),
                TaskAssignment.assigned_date >= today,
            )
        )
```

(`today` is already in scope — it's resolved a few lines above this block, at the top of the function, before it's used.)

- [ ] **Step 2: Add the regression test**

In `backend/tests/test_task_scheduling_enhancements.py`, line 18 currently reads:

```python
from app.models.task_assignment import TaskAssignment
```

Change to:

```python
from app.models.task_assignment import TaskAssignment, AssignmentStatus
```

(`_direct_assignment` is already imported from `tests.test_task_forensic_fixes` in this file — no other import changes needed.)

Then, in the `TestDaysOfWeek` class, immediately after the existing `test_auto_weekly_slot_never_lands_on_past_day` method (currently the last method in that class, right before `class TestAutoShuffle:` starts), add:

```python
    async def test_reshuffle_preserves_stale_pending_row_on_past_day(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """A PENDING row on a day that's already past — but not yet flipped
        to OVERDUE by the hourly sweep — must survive a same-week
        re-shuffle. The delete must gate on the date itself, not depend on
        the sweep having already run (prod gap: a reshuffle inside that
        window used to silently delete it and never recreate it)."""
        monday = _week_monday()
        wednesday = monday + timedelta(days=2)
        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Daily Chore", interval_days=1,
        )
        stale = await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id, monday,
        )

        await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, week_of=monday, today=wednesday
        )

        survived = await db_session.get(TaskAssignment, stale.id)
        assert survived is not None
        assert survived.status == AssignmentStatus.PENDING
```

- [ ] **Step 3: Run the new test**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_task_scheduling_enhancements.py -v`
Expected: all tests pass, including the new `test_reshuffle_preserves_stale_pending_row_on_past_day`.

- [ ] **Step 4: Run the full shuffle-related suite (regression check)**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_shuffle_logic.py tests/test_task_scheduling_enhancements.py tests/test_gig_rotation_shuffle.py tests/test_w4_task_mechanics.py -v`
Expected: all pass — confirms the new date condition doesn't break any existing mid-week/rotation/rest-day shuffle behavior (these are the suites that exercise `shuffle_tasks_detailed` most directly).

- [ ] **Step 5: Lint**

Run: `cd backend && ruff check app`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/task_assignment_service.py backend/tests/test_task_scheduling_enhancements.py
git commit -m "fix(tasks): shuffle never deletes a past-day PENDING row, regardless of overdue-sweep timing"
```
