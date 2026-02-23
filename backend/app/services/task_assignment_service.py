"""
TaskAssignment Service

Business logic for task assignments, weekly shuffle, completion, and bonus gating.
"""

import random
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, delete as sql_delete
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, date, timedelta
from uuid import UUID

from app.models.task_template import TaskTemplate
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.user import User
from app.models.point_transaction import PointTransaction, TransactionType
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)
from app.services.base_service import (
    BaseFamilyService,
    verify_user_in_family,
    get_user_by_id,
)


class TaskAssignmentService(BaseFamilyService[TaskAssignment]):
    """Service for task assignment operations including shuffle and gating"""

    model = TaskAssignment

    # ─── Shuffle Algorithm ───────────────────────────────────────────

    @staticmethod
    def _get_monday(d: date) -> date:
        """Get the Monday of the week containing the given date"""
        return d - timedelta(days=d.weekday())

    @staticmethod
    def _expand_dates(week_monday: date, interval_days: int) -> List[date]:
        """
        Expand a template into specific dates for the week based on interval_days.

        interval_days=1 -> [Mon, Tue, Wed, Thu, Fri, Sat, Sun]
        interval_days=2 -> [Mon, Wed, Fri, Sun]
        interval_days=3 -> [Mon, Thu, Sun]
        interval_days=7 -> [Mon]
        """
        dates = []
        current = week_monday
        week_end = week_monday + timedelta(days=6)  # Sunday
        while current <= week_end:
            dates.append(current)
            current += timedelta(days=interval_days)
        return dates

    @staticmethod
    async def shuffle_tasks(
        db: AsyncSession,
        family_id: UUID,
        week_of: Optional[date] = None,
    ) -> List[TaskAssignment]:
        """
        Generate weekly task assignments by shuffling templates across family members.

        Algorithm:
        1. Get all active non-bonus templates for the family
        2. Get all family members
        3. Delete existing PENDING assignments for this week (idempotent re-shuffle)
        4. Expand each template into date instances based on interval_days
        5. Shuffle all instances randomly
        6. Distribute via round-robin to ensure equal count per person
        7. Create TaskAssignment records

        Also generates bonus task assignments (assigned to all members).
        """
        # Determine the Monday of the target week
        if week_of is None:
            today = date.today()
            # If called on Sunday, target next week; otherwise target current week
            if today.weekday() == 6:  # Sunday
                week_monday = today + timedelta(days=1)
            else:
                week_monday = TaskAssignmentService._get_monday(today)
        else:
            week_monday = TaskAssignmentService._get_monday(week_of)

        # 1. Get active templates
        regular_query = select(TaskTemplate).where(
            and_(
                TaskTemplate.family_id == family_id,
                TaskTemplate.is_active == True,
                TaskTemplate.is_bonus == False,
            )
        )
        regular_templates = list(
            (await db.execute(regular_query)).scalars().all()
        )

        bonus_query = select(TaskTemplate).where(
            and_(
                TaskTemplate.family_id == family_id,
                TaskTemplate.is_active == True,
                TaskTemplate.is_bonus == True,
            )
        )
        bonus_templates = list(
            (await db.execute(bonus_query)).scalars().all()
        )

        # 2. Get all active family members
        members_query = select(User).where(
            and_(
                User.family_id == family_id,
                User.is_active == True,
            )
        )
        members = list((await db.execute(members_query)).scalars().all())

        if not members:
            raise ValidationException("No active family members found")

        # 3. Delete existing PENDING assignments for this week (re-shuffle is idempotent)
        delete_stmt = sql_delete(TaskAssignment).where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.week_of == week_monday,
                TaskAssignment.status == AssignmentStatus.PENDING,
            )
        )
        await db.execute(delete_stmt)

        assignments: List[TaskAssignment] = []

        # 4. Expand regular templates into (template, date) instances
        instances = []
        for template in regular_templates:
            dates = TaskAssignmentService._expand_dates(
                week_monday, template.interval_days
            )
            for d in dates:
                instances.append((template, d))

        # 5. Shuffle randomly
        random.shuffle(instances)

        # 6. Distribute via round-robin
        for i, (template, assigned_date) in enumerate(instances):
            member = members[i % len(members)]
            assignment = TaskAssignment(
                template_id=template.id,
                assigned_to=member.id,
                family_id=family_id,
                status=AssignmentStatus.PENDING,
                assigned_date=assigned_date,
                week_of=week_monday,
            )
            db.add(assignment)
            assignments.append(assignment)

        # 7. Bonus templates — assign to ALL members on their dates
        for template in bonus_templates:
            dates = TaskAssignmentService._expand_dates(
                week_monday, template.interval_days
            )
            for d in dates:
                for member in members:
                    assignment = TaskAssignment(
                        template_id=template.id,
                        assigned_to=member.id,
                        family_id=family_id,
                        status=AssignmentStatus.PENDING,
                        assigned_date=d,
                        week_of=week_monday,
                    )
                    db.add(assignment)
                    assignments.append(assignment)

        await db.commit()

        # Refresh all assignments to get IDs
        for assignment in assignments:
            await db.refresh(assignment)

        return assignments

    # ─── Assignment Queries ──────────────────────────────────────────

    @staticmethod
    async def get_assignment(
        db: AsyncSession, assignment_id: UUID, family_id: UUID
    ) -> TaskAssignment:
        """Get an assignment by ID with template eagerly loaded"""
        query = (
            select(TaskAssignment)
            .options(selectinload(TaskAssignment.template))
            .where(
                and_(
                    TaskAssignment.id == assignment_id,
                    TaskAssignment.family_id == family_id,
                )
            )
        )
        result = await db.execute(query)
        assignment = result.scalar_one_or_none()
        if not assignment:
            raise NotFoundException("Assignment not found")
        return assignment

    @staticmethod
    async def list_assignments_for_week(
        db: AsyncSession,
        family_id: UUID,
        week_of: date,
        user_id: Optional[UUID] = None,
        status: Optional[AssignmentStatus] = None,
    ) -> List[TaskAssignment]:
        """List assignments for a given week"""
        week_monday = TaskAssignmentService._get_monday(week_of)

        query = (
            select(TaskAssignment)
            .options(selectinload(TaskAssignment.template))
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.week_of == week_monday,
                )
            )
        )

        if user_id:
            query = query.where(TaskAssignment.assigned_to == user_id)
        if status:
            query = query.where(TaskAssignment.status == status)

        query = query.order_by(
            TaskAssignment.assigned_date.asc(), TaskAssignment.created_at.asc()
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def list_assignments_for_date(
        db: AsyncSession,
        family_id: UUID,
        target_date: date,
        user_id: Optional[UUID] = None,
    ) -> List[TaskAssignment]:
        """List assignments for a specific date"""
        query = (
            select(TaskAssignment)
            .options(selectinload(TaskAssignment.template))
            .where(
                and_(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date == target_date,
                )
            )
        )

        if user_id:
            query = query.where(TaskAssignment.assigned_to == user_id)

        query = query.order_by(TaskAssignment.created_at.asc())
        result = await db.execute(query)
        return list(result.scalars().all())

    # ─── Completion + Gating ─────────────────────────────────────────

    @staticmethod
    async def check_all_required_done_today(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        target_date: Optional[date] = None,
    ) -> bool:
        """
        Check if a user has completed all non-bonus assignments for today.
        This is the gating check for bonus task access.
        """
        check_date = target_date or date.today()

        # Count required (non-bonus) assignments for today
        total_query = (
            select(func.count())
            .select_from(TaskAssignment)
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.assigned_to == user_id,
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date == check_date,
                    TaskTemplate.is_bonus == False,
                )
            )
        )
        total = (await db.execute(total_query)).scalar_one()

        if total == 0:
            # No required tasks today — bonus unlocked
            return True

        # Count completed required assignments for today
        completed_query = (
            select(func.count())
            .select_from(TaskAssignment)
            .join(TaskTemplate, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.assigned_to == user_id,
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_date == check_date,
                    TaskTemplate.is_bonus == False,
                    TaskAssignment.status == AssignmentStatus.COMPLETED,
                )
            )
        )
        completed = (await db.execute(completed_query)).scalar_one()

        return completed >= total

    @staticmethod
    async def complete_assignment(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        user_id: UUID,
    ) -> TaskAssignment:
        """
        Mark an assignment as completed, award points, and enforce bonus gating.
        """
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )

        # Validate assignment can be completed
        if not assignment.can_complete:
            raise ValidationException(
                f"Assignment cannot be completed. Current status: {assignment.status.value}"
            )

        # Verify user is the assigned user
        if assignment.assigned_to != user_id:
            raise ForbiddenException(
                "Only the assigned user can complete this assignment"
            )

        # Check bonus gating: if this is a bonus task, required tasks must be done first
        template = assignment.template
        if template.is_bonus:
            all_required_done = (
                await TaskAssignmentService.check_all_required_done_today(
                    db, user_id, family_id, assignment.assigned_date
                )
            )
            if not all_required_done:
                raise ForbiddenException(
                    "Complete all required tasks for today before accessing bonus tasks"
                )

        # Mark as completed
        assignment.status = AssignmentStatus.COMPLETED
        assignment.completed_at = datetime.utcnow()

        # Award points
        user = await get_user_by_id(db, user_id)
        transaction = PointTransaction.create_assignment_completion(
            user_id=user_id,
            assignment_id=assignment.id,
            points=template.points,
            balance_before=user.points,
        )
        user.points += template.points

        db.add(transaction)
        await db.commit()
        await db.refresh(assignment)

        return assignment

    # ─── Daily Progress ──────────────────────────────────────────────

    @staticmethod
    async def get_daily_progress(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        target_date: Optional[date] = None,
    ) -> dict:
        """
        Get daily progress summary for a user.
        Returns required/bonus counts and whether bonus is unlocked.
        """
        check_date = target_date or date.today()

        assignments = await TaskAssignmentService.list_assignments_for_date(
            db, family_id, check_date, user_id
        )

        required_assignments = [a for a in assignments if not a.template.is_bonus]
        bonus_assignments = [a for a in assignments if a.template.is_bonus]

        required_completed = sum(
            1 for a in required_assignments if a.status == AssignmentStatus.COMPLETED
        )
        bonus_completed = sum(
            1 for a in bonus_assignments if a.status == AssignmentStatus.COMPLETED
        )

        bonus_unlocked = required_completed >= len(required_assignments)

        return {
            "date": check_date,
            "required_total": len(required_assignments),
            "required_completed": required_completed,
            "bonus_unlocked": bonus_unlocked,
            "bonus_total": len(bonus_assignments),
            "bonus_completed": bonus_completed,
            "assignments": assignments,
        }

    # ─── Overdue Check ───────────────────────────────────────────────

    @staticmethod
    async def check_overdue_assignments(
        db: AsyncSession, family_id: UUID
    ) -> List[TaskAssignment]:
        """Check for overdue assignments and update their status"""
        today = date.today()

        query = select(TaskAssignment).where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.status == AssignmentStatus.PENDING,
                TaskAssignment.assigned_date < today,
            )
        )

        assignments = list((await db.execute(query)).scalars().all())

        for assignment in assignments:
            assignment.status = AssignmentStatus.OVERDUE

        if assignments:
            await db.commit()

        return assignments
