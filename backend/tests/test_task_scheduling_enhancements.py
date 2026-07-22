"""Scheduling enhancements: specific-weekday templates + weekly auto-shuffle.

- ``days_of_week`` (list of ints, Mon=0..Sun=6) on a template refines the
  weekly expansion to exactly those weekdays — "Mon/Wed/Fri" instead of the
  rigid every-N-days pattern (a daily+rotate chore in a 2-person family
  otherwise reads as "sweep every other day" with no way to say which days).
- ``auto_shuffle_all`` generates the current week automatically for families
  that already use the shuffle (have historical assignments) but haven't
  generated the current week — creating a chore no longer schedules nothing
  until a parent remembers to press Shuffle on Monday.
"""

import pytest
from datetime import date, timedelta

from sqlalchemy import select

from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.task_template import AssignmentType
from tests.test_task_forensic_fixes import (
    _direct_assignment,
    _extra_user,
    _template,
    _week_monday,
)
from app.services.task_assignment_service import TaskAssignmentService


class TestDaysOfWeek:
    async def test_days_of_week_expands_to_those_days_only(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        monday = _week_monday()
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="MWF Chore", interval_days=1, days_of_week=[0, 2, 4],
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, today=monday
        )
        assert len(assignments) == 3
        weekdays = sorted(a.assigned_date.weekday() for a in assignments)
        assert weekdays == [0, 2, 4]

    async def test_days_of_week_rotation_alternates_members(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        monday = _week_monday()
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="MonThu Rotate", assignment_type=AssignmentType.ROTATE,
            interval_days=1, days_of_week=[0, 3],
            assigned_user_ids=[test_parent_user.id, test_child_user.id],
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, today=monday
        )
        assert len(assignments) == 2
        assert {a.assigned_to for a in assignments} == {
            test_parent_user.id, test_child_user.id
        }


class TestMidweekBalance:
    """Mid-week shuffles must stay honest and balanced.

    Prod report (2026-07-09 screenshot): preview header said Ariana had
    90 pts while her listed plan showed 2 chores (20 pts) — totals counted
    full-week occurrences whose days were already past. And because every
    rotation started at position 0 with the same member order, the SAME
    member always held the Monday slot of every template, so a mid-week
    shuffle dropped that member's turn in ALL of them at once.
    """

    async def test_preview_totals_match_listed_plan(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        monday = _week_monday()
        thursday = monday + timedelta(days=3)
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Daily Rot", assignment_type=AssignmentType.ROTATE,
            interval_days=1, points=10,
        )
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Every3 Rot", assignment_type=AssignmentType.ROTATE,
            interval_days=3, points=10,
        )
        preview = await TaskAssignmentService.preview_shuffle(
            db_session, test_family.id, week_of=monday, today=thursday
        )
        listed: dict = {}
        for item in preview["assignments"]:
            listed[item["assigned_to"]] = (
                listed.get(item["assigned_to"], 0) + item["template_points"]
            )
        for member in preview["totals_by_member"]:
            assert member["points_this_week"] == listed.get(member["user_id"], 0), (
                f"{member['user_name']}: header says "
                f"{member['points_this_week']} but plan lists "
                f"{listed.get(member['user_id'], 0)}"
            )

    async def test_listless_rotation_balances_across_templates(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """Three every-3-days chores mid-week (only Thu+Sun remain): a
        rotation WITHOUT a parent-picked list must load-balance across
        templates — positional rotation (even id-staggered) can park the
        same member's turn on the dropped Monday in every template at once
        (prod: Ariana ended with 2 chores while Mayra had 7). Template ids
        are crafted to COLLIDE under any id-based stagger, so only genuine
        cross-template balancing passes."""
        from uuid import UUID as _UUID
        from app.models.task_template import TaskTemplate

        teen = await _extra_user(
            db_session, test_family.id, "teen-stagger@test.com",
        )
        monday = _week_monday()
        thursday = monday + timedelta(days=3)
        # ids 0, 7, 14: identical under any (id % 7)-style stagger.
        for k in (0, 7, 14):
            db_session.add(TaskTemplate(
                id=_UUID(int=k),
                title=f"Every3 #{k}", points=10, interval_days=3,
                assignment_type=AssignmentType.ROTATE, assigned_user_ids=None,
                family_id=test_family.id, created_by=test_parent_user.id,
                is_bonus=False,
            ))
        await db_session.commit()

        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, week_of=monday, today=thursday
        )
        assert len(assignments) == 6  # 3 templates × (Thu, Sun)
        counts = {}
        for a in assignments:
            counts[a.assigned_to] = counts.get(a.assigned_to, 0) + 1
        assert sorted(counts.values()) == [2, 2, 2], (
            f"unbalanced mid-week rotation: {counts}"
        )

    async def test_auto_weekly_slot_never_lands_on_past_day(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        """The weekly AUTO single-slot pick must choose among REMAINING days
        mid-week — picking a past day silently dropped the chore entirely."""
        monday = _week_monday()
        saturday = monday + timedelta(days=5)
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Weekly Auto", interval_days=7, points=10,
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id, week_of=monday, today=saturday
        )
        assert len(assignments) == 1
        assert assignments[0].assigned_date >= saturday

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


class TestAutoShuffle:
    async def test_auto_shuffle_generates_for_returning_family(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        monday = _week_monday()
        tmpl = await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Auto Weekly", interval_days=1,
        )
        # Historical usage: an assignment from a prior week
        await _direct_assignment(
            db_session, tmpl, test_child_user.id, test_family.id,
            monday - timedelta(weeks=1),
        )

        created = await TaskAssignmentService.auto_shuffle_all(db_session)
        assert created > 0
        rows = (await db_session.execute(
            select(TaskAssignment).where(
                TaskAssignment.family_id == test_family.id,
                TaskAssignment.week_of == monday,
            )
        )).scalars().all()
        assert rows  # current week now populated

        # Idempotent: second run creates nothing new
        again = await TaskAssignmentService.auto_shuffle_all(db_session)
        assert again == 0

    async def test_auto_shuffle_skips_family_without_history(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _template(
            db_session, test_family.id, test_parent_user.id,
            title="Never Shuffled", interval_days=1,
        )
        created = await TaskAssignmentService.auto_shuffle_all(db_session)
        assert created == 0
