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

from app.models.task_assignment import TaskAssignment
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
