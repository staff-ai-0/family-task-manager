"""
Tests for TaskAssignmentService

Tests shuffle algorithm, completion with bonus gating, daily progress,
and overdue checking.
"""

import pytest
from datetime import date, datetime, timedelta
from uuid import uuid4

from app.models.task_template import TaskTemplate
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from app.schemas.task_template import TaskTemplateCreate
from app.services.task_template_service import TaskTemplateService
from app.services.task_assignment_service import TaskAssignmentService
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)


# ─── Helpers ─────────────────────────────────────────────────────────

async def _create_template(db, family_id, parent_id, **kwargs):
    """Helper to quickly create a template"""
    defaults = {
        "title": "Test Task",
        "points": 10,
        "interval_days": 1,
        "is_bonus": False,
    }
    defaults.update(kwargs)
    data = TaskTemplateCreate(**defaults)
    return await TaskTemplateService.create_template(
        db, data, family_id, parent_id
    )


async def _create_extra_user(db, family_id, email, role=UserRole.CHILD):
    """Helper to create an additional family member"""
    user = User(
        email=email,
        password_hash=get_password_hash("password123"),
        name=email.split("@")[0].title(),
        role=role,
        family_id=family_id,
        email_verified=True,
        points=0,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ─── Shuffle Tests ───────────────────────────────────────────────────

class TestShuffle:
    async def test_shuffle_creates_assignments(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Daily Task", interval_days=1
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        # Daily task = 7 instances, distributed among 2 members
        assert len(assignments) >= 7

    async def test_shuffle_distributes_evenly(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        # Create a daily task -> 7 instances across 2 members
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Daily Task", interval_days=1
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        regular = [a for a in assignments if a.status == AssignmentStatus.PENDING]
        parent_count = sum(1 for a in regular if a.assigned_to == test_parent_user.id)
        child_count = sum(1 for a in regular if a.assigned_to == test_child_user.id)
        # Round-robin: 7 instances / 2 members => 3 and 4 or 4 and 3
        assert abs(parent_count - child_count) <= 1

    async def test_shuffle_weekly_task_creates_one_instance(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Weekly Task", interval_days=7
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        # Weekly = 1 instance only (just Monday)
        regular = [a for a in assignments]
        assert len(regular) == 1

    async def test_shuffle_bonus_assigned_to_all_members(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Bonus Daily", interval_days=1, is_bonus=True
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        # Bonus daily = 7 days * 2 members = 14 assignments
        assert len(assignments) == 14
        parent_count = sum(1 for a in assignments if a.assigned_to == test_parent_user.id)
        child_count = sum(1 for a in assignments if a.assigned_to == test_child_user.id)
        assert parent_count == 7
        assert child_count == 7

    async def test_shuffle_is_idempotent(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Daily Task", interval_days=1
        )
        first = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        second = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        # Re-shuffle deletes PENDING and recreates: should have same count
        assert len(first) == len(second)

    async def test_shuffle_no_members_raises(
        self, db_session, test_family
    ):
        # Family with no active members
        from app.models.family import Family
        empty_family = Family(name="Empty Family")
        db_session.add(empty_family)
        await db_session.commit()

        with pytest.raises(ValidationException):
            await TaskAssignmentService.shuffle_tasks(
                db_session, empty_family.id
            )

    async def test_shuffle_sets_week_of_to_monday(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Task", interval_days=7
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        for a in assignments:
            assert a.week_of.weekday() == 0  # Monday


# ─── Assignment Queries ──────────────────────────────────────────────

class TestAssignmentQueries:
    async def test_get_assignment_by_id(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Task", interval_days=7
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        fetched = await TaskAssignmentService.get_assignment(
            db_session, assignments[0].id, test_family.id
        )
        assert fetched.id == assignments[0].id
        assert fetched.template is not None  # Eagerly loaded

    async def test_get_nonexistent_assignment_raises(
        self, db_session, test_family
    ):
        with pytest.raises(NotFoundException):
            await TaskAssignmentService.get_assignment(
                db_session, uuid4(), test_family.id
            )

    async def test_list_assignments_for_week(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Daily", interval_days=1
        )
        await TaskAssignmentService.shuffle_tasks(db_session, test_family.id)

        today = date.today()
        week_list = await TaskAssignmentService.list_assignments_for_week(
            db_session, test_family.id, today
        )
        assert len(week_list) == 7  # Daily = 7 instances

    async def test_list_assignments_for_week_filter_by_user(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Daily", interval_days=1
        )
        await TaskAssignmentService.shuffle_tasks(db_session, test_family.id)

        today = date.today()
        child_list = await TaskAssignmentService.list_assignments_for_week(
            db_session, test_family.id, today, user_id=test_child_user.id
        )
        # Should have some assignments but not all 7
        assert 0 < len(child_list) <= 7

    async def test_list_assignments_for_date(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Daily", interval_days=1
        )
        await TaskAssignmentService.shuffle_tasks(db_session, test_family.id)

        today = date.today()
        today_list = await TaskAssignmentService.list_assignments_for_date(
            db_session, test_family.id, today
        )
        # Daily task: exactly 1 instance for today (assigned to one member by round-robin)
        assert len(today_list) == 1


# ─── Completion + Gating ─────────────────────────────────────────────

class TestCompletion:
    async def test_complete_regular_assignment(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Task", interval_days=7, points=50
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        # Find the assignment for whichever member it was assigned to
        a = assignments[0]
        initial_points = 0
        await db_session.refresh(a)

        # Get the user this was assigned to
        user_id = a.assigned_to
        from app.services.base_service import get_user_by_id
        user = await get_user_by_id(db_session, user_id)
        initial_points = user.points

        completed = await TaskAssignmentService.complete_assignment(
            db_session, a.id, test_family.id, user_id
        )
        assert completed.status == AssignmentStatus.COMPLETED
        assert completed.completed_at is not None

        # Points should be awarded
        await db_session.refresh(user)
        assert user.points == initial_points + 50

    async def test_complete_already_completed_raises(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Task", interval_days=7
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        a = assignments[0]
        user_id = a.assigned_to

        await TaskAssignmentService.complete_assignment(
            db_session, a.id, test_family.id, user_id
        )
        with pytest.raises(ValidationException):
            await TaskAssignmentService.complete_assignment(
                db_session, a.id, test_family.id, user_id
            )

    async def test_complete_wrong_user_raises(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Task", interval_days=7
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )
        a = assignments[0]
        # Try completing with a different user than assigned
        wrong_user_id = (
            test_child_user.id if a.assigned_to == test_parent_user.id
            else test_parent_user.id
        )
        with pytest.raises(ForbiddenException):
            await TaskAssignmentService.complete_assignment(
                db_session, a.id, test_family.id, wrong_user_id
            )


class TestBonusGating:
    async def test_bonus_blocked_when_required_incomplete(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        # Create a regular daily + bonus daily
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Required", interval_days=7, is_bonus=False
        )
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Bonus", interval_days=7, is_bonus=True
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )

        # Find the bonus assignment for the child
        bonus_assignments = [
            a for a in assignments
            if a.assigned_to == test_child_user.id
        ]
        # Find bonus assignment
        bonus_a = None
        for a in bonus_assignments:
            await db_session.refresh(a)
            tmpl = await TaskTemplateService.get_template(
                db_session, a.template_id, test_family.id
            )
            if tmpl.is_bonus:
                bonus_a = a
                break

        if bonus_a:
            # Check if there are required assignments for the child on the same date
            required_for_child = [
                a for a in assignments
                if a.assigned_to == test_child_user.id
                and a.id != bonus_a.id
            ]

            if required_for_child:
                # Try to complete bonus without completing required first
                with pytest.raises(ForbiddenException):
                    await TaskAssignmentService.complete_assignment(
                        db_session, bonus_a.id, test_family.id, test_child_user.id
                    )

    async def test_bonus_allowed_when_all_required_done(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        # Create only a bonus weekly template (no required tasks)
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Bonus Only", interval_days=7, is_bonus=True, points=30
        )
        assignments = await TaskAssignmentService.shuffle_tasks(
            db_session, test_family.id
        )

        # Find bonus assignment for child
        child_bonus = [a for a in assignments if a.assigned_to == test_child_user.id]
        if child_bonus:
            # Should succeed: no required tasks means bonus unlocked
            completed = await TaskAssignmentService.complete_assignment(
                db_session, child_bonus[0].id, test_family.id, test_child_user.id
            )
            assert completed.status == AssignmentStatus.COMPLETED

    async def test_check_all_required_done_true_when_no_required(
        self, db_session, test_family, test_child_user
    ):
        result = await TaskAssignmentService.check_all_required_done_today(
            db_session, test_child_user.id, test_family.id
        )
        assert result is True  # No required tasks = unlocked


# ─── Daily Progress ──────────────────────────────────────────────────

class TestDailyProgress:
    async def test_progress_returns_correct_counts(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Required", interval_days=1, is_bonus=False
        )
        await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Bonus", interval_days=1, is_bonus=True
        )
        await TaskAssignmentService.shuffle_tasks(db_session, test_family.id)

        progress = await TaskAssignmentService.get_daily_progress(
            db_session, test_child_user.id, test_family.id
        )
        assert "required_total" in progress
        assert "required_completed" in progress
        assert "bonus_unlocked" in progress
        assert "bonus_total" in progress
        assert "bonus_completed" in progress
        assert "assignments" in progress
        assert progress["required_completed"] == 0
        assert progress["bonus_completed"] == 0

    async def test_progress_empty_when_no_assignments(
        self, db_session, test_family, test_child_user
    ):
        progress = await TaskAssignmentService.get_daily_progress(
            db_session, test_child_user.id, test_family.id
        )
        assert progress["required_total"] == 0
        assert progress["bonus_total"] == 0
        assert progress["bonus_unlocked"] is True  # No required = unlocked


# ─── Overdue Check ───────────────────────────────────────────────────

class TestOverdueCheck:
    async def test_overdue_marks_past_pending_assignments(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        # Create a manual assignment in the past
        template = await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Old Task", interval_days=7
        )
        yesterday = date.today() - timedelta(days=1)
        past_monday = yesterday - timedelta(days=yesterday.weekday())
        past_assignment = TaskAssignment(
            template_id=template.id,
            assigned_to=test_child_user.id,
            family_id=test_family.id,
            status=AssignmentStatus.PENDING,
            assigned_date=yesterday,
            week_of=past_monday,
        )
        db_session.add(past_assignment)
        await db_session.commit()
        await db_session.refresh(past_assignment)

        overdue_list = await TaskAssignmentService.check_overdue_assignments(
            db_session, test_family.id
        )
        assert len(overdue_list) >= 1
        assert any(a.id == past_assignment.id for a in overdue_list)

        await db_session.refresh(past_assignment)
        assert past_assignment.status == AssignmentStatus.OVERDUE

    async def test_overdue_does_not_affect_today_assignments(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        template = await _create_template(
            db_session, test_family.id, test_parent_user.id,
            title="Today Task", interval_days=7
        )
        today = date.today()
        today_monday = today - timedelta(days=today.weekday())
        today_assignment = TaskAssignment(
            template_id=template.id,
            assigned_to=test_child_user.id,
            family_id=test_family.id,
            status=AssignmentStatus.PENDING,
            assigned_date=today,
            week_of=today_monday,
        )
        db_session.add(today_assignment)
        await db_session.commit()
        await db_session.refresh(today_assignment)

        await TaskAssignmentService.check_overdue_assignments(
            db_session, test_family.id
        )
        await db_session.refresh(today_assignment)
        assert today_assignment.status == AssignmentStatus.PENDING


# ─── Date Expansion ──────────────────────────────────────────────────

class TestDateExpansion:
    def test_expand_daily(self):
        monday = date(2026, 2, 23)
        dates = TaskAssignmentService._expand_dates(monday, 1)
        assert len(dates) == 7
        assert dates[0] == monday
        assert dates[-1] == monday + timedelta(days=6)

    def test_expand_every_3_days(self):
        monday = date(2026, 2, 23)
        dates = TaskAssignmentService._expand_dates(monday, 3)
        # Mon, Thu, Sun = 3 dates
        assert len(dates) == 3
        assert dates[0] == monday
        assert dates[1] == monday + timedelta(days=3)
        assert dates[2] == monday + timedelta(days=6)

    def test_expand_weekly(self):
        monday = date(2026, 2, 23)
        dates = TaskAssignmentService._expand_dates(monday, 7)
        assert len(dates) == 1
        assert dates[0] == monday

    def test_get_monday(self):
        # Wednesday Feb 25 2026
        wednesday = date(2026, 2, 25)
        monday = TaskAssignmentService._get_monday(wednesday)
        assert monday == date(2026, 2, 23)
        assert monday.weekday() == 0

    def test_get_monday_from_monday(self):
        monday = date(2026, 2, 23)
        result = TaskAssignmentService._get_monday(monday)
        assert result == monday
