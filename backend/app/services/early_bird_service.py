"""Early Bird (11:00 chore deadline) DB layer. Pure rules live in
early_bird_rules.py; this module owns the queries and the point award.
See the 2026-11-07 early-bird spec."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    ValidationException,
)
from app.models.family import Family
from app.models.point_transaction import PointTransaction  # noqa: F401
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.services.early_bird_rules import (
    CoveredRow,
    PENDING_GRACE_DAYS,
    EarlyBirdConfig,
    chore_state,
    day_result,
    day_times,
    early_bonus_points,
    is_active_day,
    week_bonus,
    week_eligible,
    week_result,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GrabRow:
    assignment_id: UUID
    title: str
    title_es: Optional[str]
    points: int
    owner_id: UUID
    owner_name: str


class EarlyBirdService:
    # ---------------------------------------------------------------- queries

    @staticmethod
    async def config(db: AsyncSession, family_id: UUID) -> EarlyBirdConfig:
        fam = (await db.execute(select(Family).where(Family.id == family_id))).scalar_one()
        return EarlyBirdConfig.from_family(fam)

    @staticmethod
    def _covered_stmt(
        family_id: UUID, start: date, end: date, user_id: Optional[UUID] = None
    ) -> Select:
        """THE "covered by the deadline" predicate (user_id None = whole family)."""
        stmt = (
            select(TaskAssignment)
            .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
            .join(User, User.id == TaskAssignment.assigned_to)
            .where(
                TaskAssignment.family_id == family_id,
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
        if user_id is not None:
            stmt = stmt.where(TaskAssignment.assigned_to == user_id)
        return stmt

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
        stmt = EarlyBirdService._covered_stmt(family_id, start, end, user_id)
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

    # ------------------------------------------------------------ week result

    @staticmethod
    async def week_status(
        db: AsyncSession,
        cfg: EarlyBirdConfig,
        family_id: UUID,
        user_id: UUID,
        monday: date,
        now: datetime,
    ) -> tuple[str, dict[date, str]]:
        """(week_result, {day: day_result}) for Mon..Sun of ``monday``. THE
        single place a week's result is computed. Days without covered rows are
        absent (neutral). A review still pending counts once the week is
        PENDING_GRACE_DAYS past its end."""
        sunday = monday + timedelta(days=6)
        today = now.astimezone(cfg.tz).date()
        week_over = today > sunday
        grace = today > sunday + timedelta(days=PENDING_GRACE_DAYS)
        rows = await EarlyBirdService.covered_rows(db, cfg, family_id, user_id, monday, sunday)
        by_day: dict[date, list[str]] = {}
        for r in rows:
            by_day.setdefault(r.assigned_date, []).append(
                chore_state(r, cfg, now, grace=grace)
            )
        days = {d: day_result(states) for d, states in by_day.items()}
        result = week_result(
            list(days.values()), eligible=week_eligible(cfg, monday), week_over=week_over
        )
        return result, days

    @staticmethod
    async def week_bonus_cents(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        monday: date,
        base_cents: int,
        now: Optional[datetime] = None,
    ) -> int:
        """The +week_pct % on a chore paycheck of ``base_cents`` (0 unless the
        week is a clean early week)."""
        cfg = await EarlyBirdService.config(db, family_id)
        if not cfg.enabled or cfg.week_pct <= 0 or base_cents <= 0:
            return 0
        result, _ = await EarlyBirdService.week_status(
            db, cfg, family_id, user_id, monday, EarlyBirdService._now(now)
        )
        return week_bonus(base_cents, cfg.week_pct, result)

    # ------------------------------------------------------------ up for grabs

    @staticmethod
    def _now(now: Optional[datetime]) -> datetime:
        return now if now is not None else datetime.now(timezone.utc)

    @staticmethod
    async def grabbable(
        db: AsyncSession, family_id: UUID, now: Optional[datetime] = None
    ) -> list[GrabRow]:
        """Teens' still-open covered chores for family-local today, once the
        deadline has passed."""
        cfg = await EarlyBirdService.config(db, family_id)
        now = EarlyBirdService._now(now)
        today = now.astimezone(cfg.tz).date()
        if not is_active_day(cfg, today) or now < day_times(cfg, today).deadline:
            return []
        stmt = (
            EarlyBirdService._covered_stmt(family_id, today, today)
            .where(TaskAssignment.status.in_(
                [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]))
            .options(selectinload(TaskAssignment.template),
                     selectinload(TaskAssignment.assigned_user))
        )
        return [
            GrabRow(
                assignment_id=a.id,
                title=a.template.title,
                title_es=getattr(a.template, "title_es", None),
                points=int(a.template.effective_points),
                owner_id=a.assigned_to,
                owner_name=a.assigned_user.name,
            )
            for a in (await db.execute(stmt)).scalars().all()
        ]

    @staticmethod
    async def can_take(
        db: AsyncSession, taker: User, template: TaskTemplate,
        today: Optional[date] = None,
    ) -> Optional[str]:
        """Reason key the taker may not take this chore, or None."""
        from app.services.task_assignment_service import TaskAssignmentService as TAS

        if taker.role not in (UserRole.CHILD, UserRole.TEEN):
            return "not_kid"
        participates = (await db.execute(
            select(func.count()).select_from(User).where(
                User.id == taker.id, TAS._participating_member_clause())
        )).scalar_one()
        if not participates:
            return "not_kid"
        if template.allowed_roles and taker.role.value not in template.allowed_roles:
            return "role_not_allowed"
        if today is None:
            today = await TAS._family_local_today(db, taker.family_id)
        if await TAS.has_open_mandatory_through(db, taker.id, taker.family_id, today):
            return "finish_yours_first"
        return None

    @staticmethod
    async def take(
        db: AsyncSession,
        family_id: UUID,
        taker: User,
        assignment_id: UUID,
        now: Optional[datetime] = None,
    ) -> TaskAssignment:
        """Take a teen's still-open chore after the deadline. Commits."""
        from app.services.notification_service import NotificationService
        from app.services.task_assignment_service import TaskAssignmentService as TAS

        owner_row = await TAS.get_assignment(db, assignment_id, family_id, for_update=True)
        if owner_row.status == AssignmentStatus.TAKEN:
            raise ConflictException("already_taken")
        if owner_row.assigned_to == taker.id:
            raise ForbiddenException("own_chore")

        cfg = await EarlyBirdService.config(db, family_id)
        now = EarlyBirdService._now(now)
        today = now.astimezone(cfg.tz).date()
        covered = (await db.execute(
            EarlyBirdService._covered_stmt(family_id, today, today)
            .where(TaskAssignment.id == assignment_id)
        )).scalar_one_or_none()
        if (
            covered is None
            or owner_row.assigned_date != today
            or owner_row.status not in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)
            or not is_active_day(cfg, today)
            or now < day_times(cfg, today).deadline
        ):
            raise ValidationException("not_grabbable")

        template = owner_row.template
        reason = await EarlyBirdService.can_take(db, taker, template, today)
        if reason is not None:
            raise ForbiddenException(reason)

        owner_id, title, taker_name = owner_row.assigned_to, template.title, taker.name
        new_row = TaskAssignment(
            family_id=family_id,
            template_id=owner_row.template_id,
            assigned_to=taker.id,
            status=AssignmentStatus.PENDING,
            assigned_date=owner_row.assigned_date,
            week_of=owner_row.week_of,
            taken_from_id=owner_row.id,
        )
        db.add(new_row)
        owner_row.status = AssignmentStatus.TAKEN
        owner_row.taken_by = taker.id
        owner_row.taken_at = now
        await db.commit()
        await db.refresh(new_row)

        try:
            await NotificationService.create_localized(
                db, family_id, "chore_taken", user_id=owner_id,
                params={"taker": taker_name, "title": title}, link="/dashboard",
            )
        except Exception:
            log.exception("chore_taken notification failed")
        return new_row

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
