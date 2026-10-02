"""UX-D4a pings: the app-icon number and the evening smart reminders for kids.

Pure rules first (no DB), then the family-scoped queries. A smart reminder's
only send record is the notification row it creates — see run_evening_sweep.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.models.gig import GigClaim, GigClaimStatus
from app.models.notification import Notification, NotificationType as NT
from app.models.push_subscription import PushSubscription
from app.models.reward import RedemptionStatus, RewardRedemption
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.services.bank_service import _safe_zoneinfo
from app.services.notification_service import NotificationService
from app.services.progress_service import KID_ROLES, ProgressService, compute_streak
from app.services.quest_service import ChoreRow, QuestService, bonus_state, chore_state, week_monday
from app.services.task_assignment_service import TaskAssignmentService

log = logging.getLogger(__name__)

# The sweep acts while the family's local hour is 18, 19 or 20. With the server
# up, the 18:00 run handles everyone; the later hours only recover a run that
# was missed. Nothing is sent after 20:59.
PING_FIRST_HOUR = 18
PING_LAST_HOUR = 20
STREAK_PING_MIN_DAYS = 3
PING_TAG = "ftm-smart"
PING_TYPES = (NT.STREAK_AT_RISK, NT.QUEST_NUDGE)
_OPEN = (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)


def in_ping_window(local_now: datetime) -> bool:
    return PING_FIRST_HOUR <= local_now.hour <= PING_LAST_HOUR


def today_facts(rows: list[ChoreRow]) -> tuple[int, bool]:
    """(open_today, day_lost) from the kid's assignments dated today.

    open_today — mandatory chores the kid can still finish. day_lost — a
    mandatory chore today is already graded missed or rejected, so finishing
    the rest cannot save the day (and a "finish it to keep it" push would lie).
    """
    chores = [r for r in rows if not r.is_bonus and r.status != AssignmentStatus.CANCELLED]
    open_today = sum(1 for r in chores if r.status in _OPEN)
    day_lost = any(r.grade == "missed" or r.approval == ApprovalStatus.REJECTED for r in chores)
    return open_today, day_lost


def streak_ping(days: int, shield_used: bool, open_today: int, day_lost: bool) -> Optional[str]:
    """Copy key for the streak-at-risk reminder, or None when it must not be sent."""
    if days < STREAK_PING_MIN_DAYS or open_today < 1 or day_lost:
        return None
    key = "streak_at_risk_last" if shield_used else "streak_at_risk_pass"
    return f"{key}_one" if open_today == 1 else key


def quest_can_do_today(quest: str, rows: list[ChoreRow], today: date, tz: ZoneInfo, gigs_open: int) -> bool:
    """Can the kid still take the quest's missing step today? `rows` are the
    kid's assignments dated today; the states are the quest's own rules."""
    live = [r for r in rows if r.status != AssignmentStatus.CANCELLED]
    chores = [r for r in live if not r.is_bonus]
    doable = any(r.status == AssignmentStatus.PENDING and chore_state(r, today, tz) == "maybe" for r in chores)
    if quest == "on_time":
        return doable
    if quest == "perfect_days":
        return doable and all(chore_state(r, today, tz) != "no" for r in chores)
    if quest == "extra_mile":
        return any(
            r.is_bonus and r.status != AssignmentStatus.COMPLETED and bonus_state(r, today) == "maybe"
            for r in live
        )
    if quest == "go_getter":
        return gigs_open > 0
    return False


def quest_ping(progress: int, target: int, rewarded: bool, can_do_today: bool, nudged_this_week: bool) -> bool:
    return not rewarded and not nudged_this_week and can_do_today and progress == target - 1


def pick_ping(streak_key: Optional[str], quest_ok: bool) -> Optional[str]:
    """At most one reminder a day: the streak one wins, the quest nudge waits."""
    if streak_key:
        return streak_key
    return "quest_nudge" if quest_ok else None


# ── Queries (family-scoped) ──────────────────────────────────────────────
class PingService:
    @staticmethod
    async def waiting_count(db: AsyncSession, user: User) -> int:
        """The app-icon number: what is waiting for this user.

        Kid/teen — the open mandatory chores their home lists (today's plus the
        carried-over ones; bonus tasks are optional and never counted).
        Parent — the review queue: the three lists /parent/approvals renders.
        """
        family_id = user.family_id
        if user.role in KID_ROLES:
            today = await TaskAssignmentService._user_local_today(db, user.id)
            return int((await db.execute(
                select(func.count()).select_from(TaskAssignment)
                .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
                .where(
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.assigned_to == user.id,
                    TaskTemplate.is_bonus.is_(False),
                    TaskAssignment.status.in_(_OPEN),
                    TaskAssignment.assigned_date <= today,
                )
            )).scalar() or 0)
        if user.role != UserRole.PARENT:
            return 0
        tasks = (await db.execute(
            select(func.count()).select_from(TaskAssignment).where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.approval_status == ApprovalStatus.PENDING,
            )
        )).scalar() or 0
        gigs = (await db.execute(
            select(func.count()).select_from(GigClaim).where(
                GigClaim.family_id == family_id,
                GigClaim.status == GigClaimStatus.COMPLETED,
            )
        )).scalar() or 0
        rewards = (await db.execute(
            select(func.count()).select_from(RewardRedemption).where(
                RewardRedemption.family_id == family_id,
                RewardRedemption.status == RedemptionStatus.PENDING.value,
            )
        )).scalar() or 0
        return int(tasks) + int(gigs) + int(rewards)

    @staticmethod
    async def waiting_count_for_id(db: AsyncSession, user_id: UUID) -> int:
        """Same count, for the push path (which only has the id)."""
        user = await db.get(User, user_id)
        return await PingService.waiting_count(db, user) if user is not None else 0

    @staticmethod
    async def _has_ping_since(db: AsyncSession, family_id: UUID, user_id: UUID, types, since: datetime) -> bool:
        """The send record: reminder rows are never deleted (the API can only
        mark them read), so "was one sent since X" is a plain row lookup."""
        return bool((await db.execute(
            select(func.count()).select_from(Notification).where(
                Notification.family_id == family_id,
                Notification.user_id == user_id,
                Notification.type.in_(types),
                Notification.created_at >= since,
            )
        )).scalar())

    @staticmethod
    async def _ping_kid(
        db: AsyncSession, fam, kid_id: UUID, role, star_mode: bool, local_now: datetime, tz: ZoneInfo,
    ) -> bool:
        """Decide and send at most one reminder for one kid. `fam` is the
        family's row (id, quest_bonus_points, enabled_modules). Read-only apart
        from the notification: never creates a quest, never pays one."""
        today = local_now.date()
        midnight = datetime.combine(today, time.min, tzinfo=tz)
        if await PingService._has_ping_since(db, fam.id, kid_id, PING_TYPES, midnight):
            return False

        rows = await QuestService._chore_rows(db, fam.id, kid_id, today, today + timedelta(days=1))
        open_today, day_lost = today_facts(rows)
        streak = compute_streak(await ProgressService.day_states(db, fam.id, kid_id, today, tz), today)
        streak_key = streak_ping(streak.days, streak.shield_used, open_today, day_lost)

        quest_ok, bonus = False, 0
        week = week_monday(today)
        if streak_key is None and int(fam.quest_bonus_points or 0) > 0:
            quest = (await QuestService._rows(db, fam.id, kid_id, [week])).get(week)
            if quest is not None and quest.rewarded_at is None and int(quest.bonus_points or 0) > 0:
                stats = await QuestService.stats_for(db, fam.id, kid_id, week, tz, today)
                gigs_open = 0
                if quest.quest == "go_getter":
                    gigs_open = await QuestService._open_gigs(
                        db, fam.id, kid_id, role, star_mode, fam.enabled_modules,
                    )
                bonus = int(quest.bonus_points)
                quest_ok = quest_ping(
                    min(int(stats.done.get(quest.quest, 0)), int(quest.target)),
                    int(quest.target),
                    False,
                    quest_can_do_today(quest.quest, rows, today, tz, gigs_open),
                    await PingService._has_ping_since(
                        db, fam.id, kid_id, (NT.QUEST_NUDGE,), datetime.combine(week, time.min, tzinfo=tz),
                    ),
                )

        key = pick_ping(streak_key, quest_ok)
        if key is None:
            return False
        if key == "quest_nudge":
            params = {"bonus": bonus}
            expires = datetime.combine(week + timedelta(days=7), time.min, tzinfo=tz)
        else:
            params = {"days": int(streak.days), "n": int(open_today)}
            expires = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
        await NotificationService.create_localized(
            db, fam.id, key, user_id=kid_id, params=params, link="/dashboard",
            expires_at=expires, push_tag=PING_TAG,
        )
        return True

    @staticmethod
    async def run_evening_sweep(db: AsyncSession, now: Optional[datetime] = None) -> int:
        """Hourly, across ALL families: the evening smart reminders for kids.

        Acts on a family while its local hour is 18–20 (see PING_FIRST_HOUR).
        Idempotent per kid per family-local day: a kid who already has a
        reminder row since local midnight is skipped, so the 19:00 and 20:00
        runs (and a restart) never double-send. Only kids with a push
        subscription are considered — without one there is no push, and a row
        first read tomorrow would be false by then. Returns the number sent.
        """
        now = now or datetime.now(timezone.utc)
        # Plain rows, not ORM entities: a per-kid rollback below would expire
        # entities, and touching one afterwards is a lazy load in async code.
        families = (await db.execute(
            select(Family.id, Family.timezone, Family.quest_bonus_points, Family.enabled_modules).where(
                Family.deleted_at.is_(None),
                Family.smart_reminders_enabled.is_(True),
            )
        )).all()
        in_window = checked = sent = 0
        for fam in families:
            tz = _safe_zoneinfo(fam.timezone)
            local_now = now.astimezone(tz)
            if not in_ping_window(local_now):
                continue
            in_window += 1
            kids = (await db.execute(
                select(User.id, User.role, User.star_mode).where(
                    User.family_id == fam.id,
                    User.role.in_(KID_ROLES),
                    TaskAssignmentService._participating_member_clause(),
                    exists().where(PushSubscription.user_id == User.id),
                )
            )).all()
            for kid in kids:
                checked += 1
                try:
                    if await PingService._ping_kid(db, fam, kid.id, kid.role, bool(kid.star_mode), local_now, tz):
                        sent += 1
                except Exception:
                    log.exception("smart reminder failed for user %s", kid.id)
                    await db.rollback()
        if in_window:
            log.info(
                "Smart reminder sweep: %d family(ies) in window, %d kid(s) checked, %d sent",
                in_window, checked, sent,
            )
        return sent
