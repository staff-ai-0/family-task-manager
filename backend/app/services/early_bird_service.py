"""Early Bird (11:00 chore deadline) DB layer. Pure rules live in
early_bird_rules.py; this module owns the queries and the point award.
See the 2026-11-07 early-bird spec."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.models.point_transaction import PointTransaction  # noqa: F401
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.services.early_bird_rules import (
    CoveredRow,
    EarlyBirdConfig,
    day_times,
    early_bonus_points,
    is_active_day,
)


class EarlyBirdService:
    # ---------------------------------------------------------------- queries

    @staticmethod
    async def config(db: AsyncSession, family_id: UUID) -> EarlyBirdConfig:
        fam = (await db.execute(select(Family).where(Family.id == family_id))).scalar_one()
        return EarlyBirdConfig.from_family(fam)

    @staticmethod
    async def covered_rows(
        db: AsyncSession,
        cfg: EarlyBirdConfig,
        family_id: UUID,
        user_id: UUID,
        start: date,
        end: date,
    ) -> list[CoveredRow]:
        """A teen's chores covered by the deadline, start..end inclusive."""
        stmt = (
            select(TaskAssignment)
            .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
            .join(User, User.id == TaskAssignment.assigned_to)
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.assigned_date >= start,
                TaskAssignment.assigned_date <= end,
                TaskAssignment.taken_from_id.is_(None),
                TaskAssignment.status != AssignmentStatus.CANCELLED,
                TaskTemplate.is_bonus.is_(False),
                TaskTemplate.early_bird_exempt.is_(False),
                User.role == UserRole.TEEN,
            )
            .order_by(TaskAssignment.assigned_date)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            CoveredRow(
                assignment_id=a.id,
                assigned_date=a.assigned_date,
                status=a.status,
                approval=a.approval_status,
                grade=a.completion_grade,
                completed_at=a.completed_at,
            )
            for a in rows
            if is_active_day(cfg, a.assigned_date)
        ]

    # ------------------------------------------------------------ bonus award

    @staticmethod
    async def maybe_award_early_bonus(
        db: AsyncSession,
        assignment: TaskAssignment,
        template: TaskTemplate,
        *,
        credit_pct: int = 100,
    ) -> int:
        """Award the early bonus if the chore qualifies. No commit.

        Returns the points awarded (0 when not eligible). Idempotent via
        assignment.early_bonus_points.
        """
        from app.services.points_service import PointsService

        if (
            template.is_bonus
            or template.early_bird_exempt
            or assignment.taken_from_id is not None
            or assignment.early_bonus_points is not None
            or credit_pct != 100
            or assignment.completed_at is None
        ):
            return 0
        cfg = await EarlyBirdService.config(db, assignment.family_id)
        if not cfg.enabled or cfg.bonus_pct <= 0:
            return 0
        owner = (
            await db.execute(select(User).where(User.id == assignment.assigned_to))
        ).scalar_one_or_none()
        if owner is None or owner.role != UserRole.TEEN:
            return 0
        if not is_active_day(cfg, assignment.assigned_date):
            return 0
        if not assignment.completed_at < day_times(cfg, assignment.assigned_date).r1:
            return 0
        pts = early_bonus_points(template.effective_points, cfg.bonus_pct)
        if pts <= 0:
            return 0
        await PointsService.award_bonus_points(
            db, assignment.assigned_to, assignment.family_id, pts,
            f"Madrugador +{pts}", assignment_id=assignment.id,
        )
        assignment.early_bonus_points = pts
        return pts
