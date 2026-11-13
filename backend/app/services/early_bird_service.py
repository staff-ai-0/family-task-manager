"""Early Bird (11:00 chore deadline) DB layer. Pure rules live in
early_bird_rules.py; this module owns the queries and the point award.
See the 2026-11-07 early-bird spec."""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    ValidationException,
)
from app.models.cash_transaction import CashTransactionType
from app.models.early_bird_week import EarlyBirdWeek
from app.models.family import Family
from app.models.notification import NotificationType as NT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.services.early_bird_rules import (
    CoveredRow,
    PENDING_GRACE_DAYS,
    SETTLE_LOOKBACK_WEEKS,
    STREAK_WEEKS,
    EarlyBirdConfig,
    LadderResult,
    chore_state,
    completed_in_time,
    day_result,
    day_times,
    done_early,
    grab_window_open,
    early_bonus_points,
    next_run,
    is_active_day,
    pays_streak,
    reminder_stage,
    role_may_take,
    week_eligible,
    week_ladder,
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
    allowed_roles: Optional[list[str]] = None


class EarlyBirdService:
    # ---------------------------------------------------------------- queries

    @staticmethod
    async def config(db: AsyncSession, family_id: UUID) -> EarlyBirdConfig:
        fam = (await db.execute(select(Family).where(Family.id == family_id))).scalar_one()
        return EarlyBirdConfig.from_family(fam)

    @staticmethod
    async def _members(db: AsyncSession, family_id: UUID, roles) -> list:
        """(id, name, role) of the family's participating members in ``roles``,
        by name. Plain rows, not ORM entities: a sweep rollback would expire
        entities mid-loop."""
        from app.services.task_assignment_service import TaskAssignmentService as TAS

        return (await db.execute(
            select(User.id, User.name, User.role).where(
                User.family_id == family_id,
                User.role.in_(roles),
                TAS._participating_member_clause(),
            ).order_by(User.name)
        )).all()

    @staticmethod
    def _covered_stmt(
        family_id: UUID, start: date, end: date, user_id: Optional[UUID] = None,
        *, any_role: bool = False,
    ) -> Select:
        """THE "covered by the deadline" predicate (user_id None = whole family).
        Teens only, as the weekly stats count them; ``any_role`` widens it to
        every member's chores (the up-for-grabs list and the cutoff expiry)."""
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
            )
            .order_by(TaskAssignment.assigned_date)
        )
        if not any_role:
            stmt = stmt.where(User.role == UserRole.TEEN)
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
                parent_marked=bool(a.marked_done_by_parent),
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
        rows = await EarlyBirdService.covered_rows(
            db, cfg, family_id, user_id, monday, monday + timedelta(days=6)
        )
        return EarlyBirdService._week_from_rows(cfg, rows, monday, now)

    @staticmethod
    def _week_from_rows(
        cfg: EarlyBirdConfig, rows: list[CoveredRow], monday: date, now: datetime
    ) -> tuple[str, dict[date, str]]:
        """week_status over already-fetched covered rows of that week."""
        sunday = monday + timedelta(days=6)
        today = now.astimezone(cfg.tz).date()
        # Controller ruling: a week is "over" for early-bird purposes at
        # Sunday's deadline (the early cutoff) — nothing earlier can still change.
        week_over = now >= day_times(cfg, sunday).deadline
        grace = today > sunday + timedelta(days=PENDING_GRACE_DAYS)
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
    async def week_metrics(
        db: AsyncSession,
        cfg: EarlyBirdConfig,
        family_id: UUID,
        user_id: UUID,
        monday: date,
        now: datetime,
    ) -> LadderResult:
        """THE single source of a week's percentages: the ladder tier + counts
        for a teen's Mon..Sun. One query (covered_rows, family-scoped)."""
        if not cfg.enabled or not week_eligible(cfg, monday):
            return week_ladder(0, 0, 0)
        rows = await EarlyBirdService.covered_rows(
            db, cfg, family_id, user_id, monday, monday + timedelta(days=6)
        )
        return EarlyBirdService._metrics_from_rows(cfg, rows, monday, now)

    @staticmethod
    def _metrics_from_rows(
        cfg: EarlyBirdConfig, rows: list[CoveredRow], monday: date, now: datetime
    ) -> LadderResult:
        """week_metrics over already-fetched covered rows of that week. Open and
        TAKEN rows count in ``total`` but not as completed (the meter is "so
        far"). ``final`` is True once Sunday's cutoff has passed AND no
        completed row still awaits the parent's review inside the pending
        grace (ruling R5): an unreviewed count can still move, so the pay
        ladder must not floor or bonus it yet. After the grace the week is
        final and those rows count via the grace rule."""
        if not cfg.enabled or not week_eligible(cfg, monday):
            return week_ladder(0, 0, 0)
        sunday = monday + timedelta(days=6)
        grace = now.astimezone(cfg.tz).date() > sunday + timedelta(days=PENDING_GRACE_DAYS)
        completed = sum(1 for r in rows if completed_in_time(r, cfg, grace=grace))
        early = sum(1 for r in rows if done_early(r, cfg, grace=grace))
        result = week_ladder(completed, early, len(rows))
        unreviewed = not grace and any(
            r.status == AssignmentStatus.COMPLETED and r.approval == ApprovalStatus.PENDING
            for r in rows
        )
        return replace(
            result, final=now >= day_times(cfg, sunday).cutoff and not unreviewed
        )

    # The weekly paycheck bonus is NOT computed here: the flat +week_pct % was
    # retired by the chore-rules-v2 pay ladder, whose money lives only in
    # BankService._ladder_adjust (fed by week_metrics above).

    # ------------------------------------------------------------ up for grabs

    @staticmethod
    def _now(now: Optional[datetime]) -> datetime:
        return now if now is not None else datetime.now(timezone.utc)

    @staticmethod
    async def grabbable(
        db: AsyncSession, family_id: UUID, now: Optional[datetime] = None
    ) -> list[GrabRow]:
        """Every member's still-open covered chores for family-local today,
        while the grab window (cutoff <= now < grab_end) is open."""
        cfg = await EarlyBirdService.config(db, family_id)
        now = EarlyBirdService._now(now)
        today = now.astimezone(cfg.tz).date()
        if not cfg.enabled or not is_active_day(cfg, today) or not grab_window_open(
            now, day_times(cfg, today)
        ):
            return []
        stmt = (
            EarlyBirdService._covered_stmt(family_id, today, today, any_role=True)
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
                allowed_roles=a.template.allowed_roles,
            )
            for a in (await db.execute(stmt)).scalars().all()
        ]

    @staticmethod
    async def _not_eligible(db: AsyncSession, taker: User, family_id: UUID) -> bool:
        """True when the taker is not an active, approved member of the family."""
        from app.services.task_assignment_service import TaskAssignmentService as TAS

        if taker.family_id != family_id:
            return True
        participates = (await db.execute(
            select(func.count()).select_from(User).where(
                User.id == taker.id, User.family_id == family_id,
                TAS._participating_member_clause())
        )).scalar_one()
        return not participates

    @staticmethod
    async def can_take(
        db: AsyncSession, taker: User, template: TaskTemplate,
        today: Optional[date] = None,
    ) -> Optional[str]:
        """Reason key the taker may not take this chore, or None. Any active,
        approved member (parents included) whose role the template allows."""
        if await EarlyBirdService._not_eligible(db, taker, template.family_id):
            return "not_eligible"
        if not role_may_take(template.allowed_roles, taker.role.value):
            return "role_not_allowed"
        return None

    @staticmethod
    async def caller_block(
        db: AsyncSession, taker: User, today: Optional[date] = None
    ) -> Optional[str]:
        """Why the taker can take NO grab at all (not_eligible), or None — the
        per-chore role rule is can_take's."""
        if await EarlyBirdService._not_eligible(db, taker, taker.family_id):
            return "not_eligible"
        return None

    @staticmethod
    async def take(
        db: AsyncSession,
        family_id: UUID,
        taker: User,
        assignment_id: UUID,
        now: Optional[datetime] = None,
    ) -> TaskAssignment:
        """Take a member's still-open chore inside the grab window. Commits."""
        from app.services.notification_service import NotificationService
        from app.services.task_assignment_service import TaskAssignmentService as TAS

        owner_row = await TAS.get_assignment(db, assignment_id, family_id, for_update=True)
        if owner_row.status == AssignmentStatus.TAKEN:
            raise ConflictException("already_taken")
        if owner_row.assigned_to == taker.id:
            raise ForbiddenException("own_chore")
        # Serialize one member's takes (locked after the owner row, fixed
        # order) so two takes by the same taker cannot interleave.
        await db.execute(select(User.id).where(User.id == taker.id).with_for_update())

        cfg = await EarlyBirdService.config(db, family_id)
        now = EarlyBirdService._now(now)
        today = now.astimezone(cfg.tz).date()
        covered = (await db.execute(
            EarlyBirdService._covered_stmt(family_id, today, today, any_role=True)
            .where(TaskAssignment.id == assignment_id)
        )).scalar_one_or_none()
        if (
            covered is None
            or owner_row.assigned_date != today
            or owner_row.status not in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)
            or not is_active_day(cfg, today)
        ):
            raise ValidationException("not_grabbable")
        if not grab_window_open(now, day_times(cfg, today)):
            raise ConflictException("grab_window_closed")

        template = owner_row.template
        reason = await EarlyBirdService.can_take(db, taker, template, today)
        if reason is not None:
            raise ForbiddenException(reason)

        owner_id, taker_name = owner_row.assigned_to, taker.name
        title = {"en": template.title, "es": template.title_es or template.title}
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

    # ------------------------------------------------------------ API payloads

    @staticmethod
    async def _teen_view(db, cfg, family_id, user_id, now) -> dict:
        """today / week / week_result / run_weeks for one teen. Reuses
        week_status; never recomputes rules."""
        today = now.astimezone(cfg.tz).date()
        monday = today - timedelta(days=today.weekday())
        rows = await EarlyBirdService.covered_rows(
            db, cfg, family_id, user_id, monday, monday + timedelta(days=6)
        )
        result, days = EarlyBirdService._week_from_rows(cfg, rows, monday, now)
        week = []
        for i in range(7):
            d = monday + timedelta(days=i)
            state = "future" if d > today else days.get(d, "neutral")
            week.append({"date": d, "state": state})
        today_state = (
            days.get(today, "neutral") if is_active_day(cfg, today) else None
        )
        last = (await db.execute(
            select(EarlyBirdWeek.run_weeks)
            .where(EarlyBirdWeek.user_id == user_id)
            .order_by(EarlyBirdWeek.week_of.desc())
            .limit(1)
        )).scalar_one_or_none()
        return {
            "today": today_state,
            "week": week,
            "week_result": result,
            "run_weeks": int(last or 0),
            "weeks_to_payout": STREAK_WEEKS - (int(last or 0) % STREAK_WEEKS),
            "streak_weeks": STREAK_WEEKS,
            "open_today": sum(
                1 for r in rows
                if r.assigned_date == today
                and r.status in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)
            ),
        }

    @staticmethod
    async def me(db: AsyncSession, user: User, now: Optional[datetime] = None) -> dict:
        """Payload for GET /api/early-bird/me."""
        now = EarlyBirdService._now(now)
        cfg = await EarlyBirdService.config(db, user.family_id)
        out = {
            "enabled": cfg.enabled,
            "applies": False,
            "deadline": cfg.deadline.strftime("%H:%M"),
            "cutoff_at": None,
            "deadline_at": None,
            "today": None,
            "week": [],
            "week_result": "ineligible",
            "run_weeks": 0,
            "weeks_to_payout": STREAK_WEEKS,
            "streak_weeks": STREAK_WEEKS,
            "streak_cents": int(cfg.streak_cents),
            "week_pct": int(cfg.week_pct),
            "bonus_pct": int(cfg.bonus_pct),
            "grabs": [],
            "take_block": None,
            "open_today": 0,
        }
        if not cfg.enabled:
            return out
        today = now.astimezone(cfg.tz).date()
        if is_active_day(cfg, today):
            t = day_times(cfg, today)
            out["cutoff_at"], out["deadline_at"] = t.deadline, t.deadline
        if user.role == UserRole.TEEN:
            out["applies"] = True
            out.update(await EarlyBirdService._teen_view(db, cfg, user.family_id, user.id, now))

        rows = await EarlyBirdService.grabbable(db, user.family_id, now)
        if rows:
            es = (getattr(user, "preferred_lang", None) or "en") == "es"
            out["grabs"] = [
                {
                    "assignment_id": g.assignment_id,
                    "title": g.title_es if (es and g.title_es) else g.title,
                    "points": g.points,
                    "owner_name": g.owner_name,
                }
                for g in rows
                if g.owner_id != user.id and role_may_take(g.allowed_roles, user.role.value)
            ]
            if out["grabs"]:
                out["take_block"] = await EarlyBirdService.caller_block(db, user, today)
        return out

    @staticmethod
    async def family_overview(
        db: AsyncSession, parent: User, now: Optional[datetime] = None
    ) -> list[dict]:
        """One entry per participating TEEN of the parent's family."""
        now = EarlyBirdService._now(now)
        cfg = await EarlyBirdService.config(db, parent.family_id)
        if not cfg.enabled:
            return []
        teens = await EarlyBirdService._members(db, parent.family_id, (UserRole.TEEN,))
        out = []
        for t in teens:
            view = await EarlyBirdService._teen_view(db, cfg, parent.family_id, t.id, now)
            out.append({"user_id": t.id, "name": t.name, **view})
        return out

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
        if not assignment.completed_at < day_times(cfg, assignment.assigned_date).deadline:
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

    # ------------------------------------------------------------------ sweep

    @staticmethod
    async def run_sweep(db: AsyncSession, now: Optional[datetime] = None) -> dict[str, int]:
        """Every ~5 min, across ALL families: deadline reminders (R1/R2) and
        the up-for-grabs pushes. The notification row is the send record
        (``PingService._has_ping_since``), so a run is idempotent per member per
        window. Unlike the evening ping sweep this does NOT require a push
        subscription: rows carry ``expires_at`` so they never go stale.
        Returns counts; ``settled``/``paid`` are filled by the settlement step."""
        now = EarlyBirdService._now(now)
        out = {"reminders": 0, "grabs": 0, "settled": 0, "paid": 0}
        # Plain rows, not ORM entities: a rollback below would expire entities.
        fam_ids = (await db.execute(
            select(Family.id).where(
                Family.deleted_at.is_(None), Family.early_bird_enabled.is_(True)
            )
        )).scalars().all()
        for fam_id in fam_ids:
            try:
                cfg = await EarlyBirdService.config(db, fam_id)
                local_now = now.astimezone(cfg.tz)
                today = local_now.date()
                if is_active_day(cfg, today):
                    await EarlyBirdService._sweep_reminders(db, cfg, fam_id, now, today, out)
                await EarlyBirdService._sweep_settle(db, cfg, fam_id, now, out)
            except Exception:
                log.exception("early bird sweep failed for family %s", fam_id)
                await db.rollback()
        return out

    @staticmethod
    async def _sweep_settle(db, cfg, fam_id, now, out) -> None:
        teens = [m.id for m in await EarlyBirdService._members(db, fam_id, (UserRole.TEEN,))]
        for uid in teens:
            try:
                settled, paid = await EarlyBirdService._settle(db, cfg, fam_id, uid, now)
                out["settled"] += settled
                out["paid"] += paid
            except Exception:
                log.exception("early bird settlement failed for user %s", uid)
                await db.rollback()

    @staticmethod
    async def _sweep_reminders(db, cfg, fam_id, now, today, out) -> None:
        times = day_times(cfg, today)
        stage = reminder_stage(now, times)
        if stage in ("r1", "r2"):
            teens = [m.id for m in await EarlyBirdService._members(db, fam_id, (UserRole.TEEN,))]
            since = times.r1 if stage == "r1" else times.r2
            for uid in teens:
                try:
                    out["reminders"] += await EarlyBirdService._remind(
                        db, cfg, fam_id, uid, today, stage, since, times.deadline
                    )
                except Exception:
                    log.exception("early bird reminder failed for user %s", uid)
                    await db.rollback()
        elif stage == "grabs":
            out["grabs"] += await EarlyBirdService._push_grabs(
                db, cfg, fam_id, now, times.cutoff, today
            )

    # ------------------------------------------------------------- settlement

    @staticmethod
    async def _settle(db, cfg, family_id, user_id, now) -> tuple[int, int]:
        """(weeks settled, payouts) for one teen's finished weeks, oldest first.
        Idempotent: UNIQUE(user_id, week_of) + ON CONFLICT DO NOTHING for the
        row, guarded UPDATE (paid_at IS NULL) for the money. One query when
        every week in the window is already settled (the 5-minute steady
        state); ineligible weeks are skipped without touching the DB."""
        this_monday = now.astimezone(cfg.tz).date()
        this_monday -= timedelta(days=this_monday.weekday())
        first = this_monday - timedelta(weeks=SETTLE_LOOKBACK_WEEKS)
        weeks = await EarlyBirdService._week_rows(
            db, user_id, first - timedelta(days=7), this_monday - timedelta(days=7)
        )
        settled = paid = 0
        for k in range(SETTLE_LOOKBACK_WEEKS, 0, -1):
            monday = this_monday - timedelta(weeks=k)
            existing = weeks.get(monday)
            if existing is None:
                if not week_eligible(cfg, monday):
                    continue
                result, _ = await EarlyBirdService.week_status(
                    db, cfg, family_id, user_id, monday, now
                )
                if result in ("pending", "in_progress"):
                    break  # later weeks wait so runs are computed in order
                prev = weeks.get(monday - timedelta(days=7))
                run = next_run(prev.run_weeks if prev is not None else 0, result)
                # The prize is fixed when the week settles (like the quest
                # bonus): a run-3 week settled under a $0 prize earned nothing,
                # and raising the prize later must not pay it retroactively.
                prize = cfg.streak_cents if pays_streak(result, run) else 0
                await db.execute(
                    pg_insert(EarlyBirdWeek)
                    .values(family_id=family_id, user_id=user_id, week_of=monday,
                            result=result, run_weeks=run, bonus_cents=max(0, prize))
                    .on_conflict_do_nothing(index_elements=["user_id", "week_of"])
                )
                await db.commit()
                existing = (await EarlyBirdService._week_rows(db, user_id, monday, monday)).get(monday)
                weeks[monday] = existing
                settled += 1
            if (
                existing is not None
                and existing.paid_at is None
                and existing.bonus_cents > 0
                and pays_streak(existing.result, existing.run_weeks)
            ):
                if await EarlyBirdService._pay_streak(
                    db, family_id, user_id, existing.id, existing.run_weeks,
                    existing.bonus_cents, now,
                ):
                    paid += 1
        return settled, paid

    @staticmethod
    async def _week_rows(db, user_id, first: date, last: date) -> dict:
        """{week_of: row} of a teen's settled weeks in [first, last]. Plain
        column rows, not entities: _pay_streak may roll back mid-loop."""
        rows = (await db.execute(
            select(
                EarlyBirdWeek.id, EarlyBirdWeek.week_of, EarlyBirdWeek.result,
                EarlyBirdWeek.run_weeks, EarlyBirdWeek.bonus_cents, EarlyBirdWeek.paid_at,
            ).where(
                EarlyBirdWeek.user_id == user_id,
                EarlyBirdWeek.week_of >= first,
                EarlyBirdWeek.week_of <= last,
            )
        )).all()
        return {r.week_of: r for r in rows}

    @staticmethod
    async def _pay_streak(db, family_id, user_id, row_id, run, cents, now) -> bool:
        from app.services.bank_service import _fmt_mxn
        from app.services.cash_service import (
            CashService,
            _get_or_create_account_locked,
            _get_user_locked,
        )
        from app.services.notification_service import NotificationService

        user = await _get_user_locked(db, user_id)
        acct = await _get_or_create_account_locked(db, user, family_id)
        res = await db.execute(
            update(EarlyBirdWeek)
            .where(EarlyBirdWeek.id == row_id, EarlyBirdWeek.paid_at.is_(None))
            .values(paid_at=now, bonus_cents=cents)
        )
        if res.rowcount != 1:
            await db.rollback()
            return False
        CashService.credit_split_rows(
            db, user, acct, family_id, cents, CashTransactionType.BONUS,
            entitled=await CashService._bank_automation_entitled(db, family_id),
            description=f"Bono madrugador {STREAK_WEEKS} semanas",
        )
        kid_name = user.name
        await db.commit()

        params = {"weeks": run, "amount": _fmt_mxn(cents)}
        try:
            await NotificationService.create_localized(
                db, family_id, "early_bird_payout_kid", user_id=user_id,
                params=params, link="/bank",
            )
        except Exception:
            log.exception("early bird payout kid notification failed")
        # Per-parent rows (a user_id=None family broadcast is never pushed and
        # would also show the teen's payout to the teen and siblings).
        try:
            parent_ids = [
                m.id for m in await EarlyBirdService._members(db, family_id, (UserRole.PARENT,))
            ]
        except Exception:
            log.exception("early bird payout parent lookup failed")
            parent_ids = []
        for pid in parent_ids:
            try:
                await NotificationService.create_localized(
                    db, family_id, "early_bird_payout_parent", user_id=pid,
                    params={**params, "kid": kid_name}, link="/parent/payouts",
                )
            except Exception:
                log.exception("early bird payout parent notification failed")
                await db.rollback()
        return True

    @staticmethod
    async def _remind(db, cfg, fam_id, uid, today, stage, since, deadline) -> int:
        from app.services.notification_service import NotificationService
        from app.services.ping_service import PingService

        rows = await EarlyBirdService.covered_rows(db, cfg, fam_id, uid, today, today)
        n = sum(1 for r in rows if r.status in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE))
        if n < 1:
            return 0
        if await PingService._has_ping_since(db, fam_id, uid, (NT.DEADLINE_SOON,), since):
            return 0
        key = f"deadline_{stage}" + ("_one" if n == 1 else "")
        await NotificationService.create_localized(
            db, fam_id, key, user_id=uid,
            params={"n": n, "deadline": cfg.deadline.strftime("%H:%M")},
            link="/dashboard", expires_at=deadline, push_tag="ftm-early-bird",
        )
        return 1

    @staticmethod
    async def _push_grabs(db, cfg, fam_id, now, since, today) -> int:
        from app.services.notification_service import NotificationService
        from app.services.ping_service import PingService

        grabs = await EarlyBirdService.grabbable(db, fam_id, now)
        if not grabs:
            return 0
        owner_n: dict[UUID, int] = {}
        for g in grabs:
            owner_n[g.owner_id] = owner_n.get(g.owner_id, 0) + 1
        members = await EarlyBirdService._members(
            db, fam_id, (UserRole.PARENT, UserRole.CHILD, UserRole.TEEN)
        )
        midnight = datetime.combine(today + timedelta(days=1), time.min, tzinfo=cfg.tz)
        sent = 0
        for uid, _name, role in members:
            try:
                if uid in owner_n:
                    n = owner_n[uid]
                    key = "grabs_owner_one" if n == 1 else "grabs_owner"
                else:
                    n = sum(1 for g in grabs if role_may_take(g.allowed_roles, role.value))
                    if n < 1:
                        continue
                    key = "grabs_open_one" if n == 1 else "grabs_open"
                if await PingService._has_ping_since(db, fam_id, uid, (NT.UP_FOR_GRABS,), since):
                    continue
                await NotificationService.create_localized(
                    db, fam_id, key, user_id=uid, params={"n": n},
                    link="/dashboard", expires_at=midnight, push_tag="ftm-early-bird",
                )
                sent += 1
            except Exception:
                log.exception("early bird grabs push failed for user %s", uid)
                await db.rollback()
        return sent
