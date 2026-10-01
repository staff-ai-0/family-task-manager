"""UX-D3 weekly quest: one personal goal per kid per week, with a points bonus
paid once when it is reached — see
docs/superpowers/specs/2026-10-01-ux-d3-weekly-quest-design.md.

Progress is derived on read (like UX-D1/D2); only the week's quest row is
stored (`weekly_quests`: type, target, bonus, paid/seen marks). This module
holds the pure rules; the DB queries live in QuestService below them.
Copy (titles, emoji) lives only in frontend/src/lib/quest.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modules import effective_modules
from app.models.family import Family
from app.models.gig import GigClaim, GigClaimStatus, GigOffering, GigOfferingStatus
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.models.weekly_quest import WeeklyQuest
from app.schemas.progress import QuestCelebrate, QuestProgress, QuestResponse
from app.services.points_service import PointsService
from app.services.progress_service import KID_ROLES, ProgressService

# Rotation order -> default goal (also the goal for a kid with no history).
QUESTS: dict[str, int] = {"on_time": 3, "extra_mile": 1, "perfect_days": 2, "go_getter": 1}
# go_getter has no "left this week" count of its own (a gig board, not dated
# rows): its goal is capped here AND by the gigs the kid could still get approved.
OPEN_ENDED_CAP = 7
HISTORY_WEEKS = 4
# Work awaiting a parent's review does not count until approved: the bonus is
# real points and is never taken back.
_COUNTING = (ApprovalStatus.NONE, ApprovalStatus.APPROVED)


def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def rotation(week_start: date, user_id: UUID) -> list[str]:
    """The four quest keys, starting at this kid's slot for this week. Each
    kid moves one step per week; siblings start at different slots."""
    keys = list(QUESTS)
    start = (week_start.toordinal() // 7 + user_id.int) % len(keys)
    return keys[start:] + keys[:start]


def size_target(default: int, history_total: int, done: int, possible: Optional[int]) -> Optional[int]:
    """Goal for one quest type, or None when it cannot be this week's quest.

    history_total — the kid's count for this type over the previous
    HISTORY_WEEKS full weeks; done — already achieved this week; possible —
    how many more can still be achieved this week (None = type not offered).
    """
    if possible is None:
        return None
    # ceil(1.1 x average) in integers: ceil(11 * total / (10 * weeks)).
    stretch = max(default, -(-history_total * 11 // (10 * HISTORY_WEEKS)))
    target = min(stretch, done + possible)
    # A quest never starts finished, and never asks for the impossible.
    return target if target >= done + 1 else None


@dataclass(frozen=True)
class ChoreRow:
    assigned_date: date
    status: AssignmentStatus
    completed_at: Optional[datetime]
    grade: Optional[str]
    approval: ApprovalStatus
    is_bonus: bool


def _on_time(row: ChoreRow, tz: ZoneInfo) -> bool:
    # Legacy rows completed before timestamps existed count as on time (D1's rule).
    return row.completed_at is None or row.completed_at.astimezone(tz).date() <= row.assigned_date


def chore_state(row: ChoreRow, today: date, tz: ZoneInfo) -> str:
    """'yes' — counts on time now · 'maybe' — can still count · 'no' — cannot."""
    if row.status == AssignmentStatus.COMPLETED:
        if row.grade == "missed" or row.approval == ApprovalStatus.REJECTED or not _on_time(row, tz):
            return "no"
        return "yes" if row.approval in _COUNTING else "maybe"
    if row.status == AssignmentStatus.PENDING and row.assigned_date >= today:
        return "maybe"
    return "no"


def bonus_state(row: ChoreRow, today: date) -> str:
    """Like chore_state, for bonus tasks: no on-time requirement.
    'yes' — counts now · 'maybe' — can still count · 'no' — cannot."""
    if row.status == AssignmentStatus.COMPLETED:
        if row.grade == "missed" or row.approval == ApprovalStatus.REJECTED:
            return "no"
        return "yes" if row.approval in _COUNTING else "maybe"
    if row.status in (AssignmentStatus.PENDING, AssignmentStatus.CLAIMED) and row.assigned_date >= today:
        return "maybe"
    return "no"


@dataclass(frozen=True)
class WeekStats:
    done: dict[str, int]       # per quest key: achieved in the period
    possible: dict[str, int]   # chore and bonus types: how many more can still count


def week_stats(rows: list[ChoreRow], gigs_approved: int, today: date, tz: ZoneInfo) -> WeekStats:
    """Counts for every quest type over the given rows (one week, or several
    for history). `possible` is meaningful for every type but go_getter, whose
    ceiling is the gig board (see pick_quest)."""
    live = [r for r in rows if r.status != AssignmentStatus.CANCELLED]
    states = [(r.assigned_date, chore_state(r, today, tz)) for r in live if not r.is_bonus]
    by_day: dict[date, list[str]] = {}
    for day, state in states:
        by_day.setdefault(day, []).append(state)
    bonus = [bonus_state(r, today) for r in live if r.is_bonus]
    return WeekStats(
        done={
            "on_time": sum(1 for _, s in states if s == "yes"),
            "perfect_days": sum(1 for ss in by_day.values() if all(s == "yes" for s in ss)),
            "extra_mile": bonus.count("yes"),
            "go_getter": int(gigs_approved),
        },
        possible={
            "on_time": sum(1 for _, s in states if s == "maybe"),
            "perfect_days": sum(1 for ss in by_day.values() if "no" not in ss and "maybe" in ss),
            "extra_mile": bonus.count("maybe"),
            "go_getter": 0,
        },
    )


def pick_quest(
    order: list[str], stats: WeekStats, history: dict[str, int], gigs_open: int,
) -> Optional[tuple[str, int]]:
    """First type in `order` that is achievable, with its goal. A type with
    nothing possible (no chores, no bonus tasks, no open gigs) is skipped."""
    for key in order:
        done = stats.done.get(key, 0)
        if key == "go_getter":
            # Open-ended in principle, but never more than the gigs on the board.
            possible = max(0, min(OPEN_ENDED_CAP - done, gigs_open))
        else:
            possible = stats.possible.get(key, 0)
        target = size_target(QUESTS[key], history.get(key, 0), done, possible)
        if target is not None:
            return key, target
    return None


# ── Queries (family-scoped) ──────────────────────────────────────────────
class QuestService:
    @staticmethod
    async def _chore_rows(
        db: AsyncSession, family_id: UUID, user_id: UUID, start: date, end: date,
    ) -> list[ChoreRow]:
        """The kid's assignments dated in [start, end)."""
        rows = (await db.execute(
            select(
                TaskAssignment.assigned_date,
                TaskAssignment.status,
                TaskAssignment.completed_at,
                TaskAssignment.completion_grade,
                TaskAssignment.approval_status,
                TaskTemplate.is_bonus,
            )
            .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.assigned_date >= start,
                TaskAssignment.assigned_date < end,
            )
        )).all()
        return [
            ChoreRow(r.assigned_date, r.status, r.completed_at, r.completion_grade, r.approval_status, bool(r.is_bonus))
            for r in rows
        ]

    @staticmethod
    async def _gigs_approved(
        db: AsyncSession, family_id: UUID, user_id: UUID, start: date, end: date, tz: ZoneInfo,
    ) -> int:
        """Gig claims approved inside [start, end), family-local days."""
        lo = datetime.combine(start, time.min, tzinfo=tz)
        hi = datetime.combine(end, time.min, tzinfo=tz)
        return int((await db.execute(
            select(func.count()).select_from(GigClaim).where(
                GigClaim.family_id == family_id,
                GigClaim.claimed_by == user_id,
                GigClaim.status == GigClaimStatus.APPROVED,
                GigClaim.approved_at >= lo,
                GigClaim.approved_at < hi,
            )
        )).scalar() or 0)

    @staticmethod
    async def stats_for(
        db: AsyncSession, family_id: UUID, user_id: UUID, week_start: date, tz: ZoneInfo, today: date,
    ) -> WeekStats:
        end = week_start + timedelta(days=7)
        return week_stats(
            await QuestService._chore_rows(db, family_id, user_id, week_start, end),
            await QuestService._gigs_approved(db, family_id, user_id, week_start, end, tz),
            today, tz,
        )

    @staticmethod
    async def _history(
        db: AsyncSession, family_id: UUID, user_id: UUID, week_start: date, tz: ZoneInfo, today: date,
    ) -> dict[str, int]:
        """Per-type totals over the HISTORY_WEEKS full weeks before week_start."""
        start = week_start - timedelta(weeks=HISTORY_WEEKS)
        return week_stats(
            await QuestService._chore_rows(db, family_id, user_id, start, week_start),
            await QuestService._gigs_approved(db, family_id, user_id, start, week_start, tz),
            today, tz,
        ).done

    @staticmethod
    async def _open_gigs(
        db: AsyncSession, family_id: UUID, user_id: UUID, role: UserRole, star_mode: bool,
        enabled_modules: Optional[Iterable[str]],
    ) -> int:
        """How many gig offerings this kid could still get approved: active,
        approved offerings open to their role, minus the ones where they
        already hold an approved claim. 0 for star-mode kids and for families
        with the gigs module off (neither has a gig board)."""
        if star_mode or "gigs" not in effective_modules(enabled_modules):
            return 0
        role_name = role.value if hasattr(role, "value") else str(role)
        offerings = (await db.execute(
            select(GigOffering.id, GigOffering.allowed_roles).where(
                GigOffering.family_id == family_id,
                GigOffering.is_active.is_(True),
                GigOffering.status == GigOfferingStatus.APPROVED.value,
            )
        )).all()
        open_ids = {
            gig_id for gig_id, allowed in offerings
            if not allowed or role_name in {str(r).lower() for r in allowed}
        }
        if not open_ids:
            return 0
        already = set((await db.execute(
            select(GigClaim.gig_id).where(
                GigClaim.family_id == family_id,
                GigClaim.claimed_by == user_id,
                GigClaim.status == GigClaimStatus.APPROVED,
            )
        )).scalars().all())
        return len(open_ids - already)

    @staticmethod
    async def _rows(
        db: AsyncSession, family_id: UUID, user_id: UUID, weeks: list[date],
    ) -> dict[date, WeeklyQuest]:
        rows = (await db.execute(
            select(WeeklyQuest).where(
                WeeklyQuest.family_id == family_id,
                WeeklyQuest.user_id == user_id,
                WeeklyQuest.week_start.in_(weeks),
            )
        )).scalars().all()
        return {q.week_start: q for q in rows}

    @staticmethod
    async def _settle(db: AsyncSession, quest: WeeklyQuest, lang: str) -> None:
        """Pay the bonus exactly once. The guarded UPDATE is the gate: of two
        requests settling the same quest, the second waits on the row lock and
        then matches nothing, so only one of them writes the transaction. The
        paid mark and the points are committed together."""
        paid = (await db.execute(
            update(WeeklyQuest)
            .where(WeeklyQuest.id == quest.id, WeeklyQuest.rewarded_at.is_(None))
            .values(rewarded_at=datetime.now(timezone.utc))
            .returning(WeeklyQuest.id)
            .execution_options(synchronize_session=False)   # the row is refreshed after the commit
        )).first()
        bonus = int(quest.bonus_points or 0)
        if paid is not None and bonus > 0:
            kid = await PointsService._get_user_locked(db, quest.user_id, quest.family_id)
            # The row is now locked, but `kid` may be the SAME object the
            # request's `get_current_user` already loaded into this session
            # earlier (identity map, `expire_on_commit=False`) — the locked
            # SELECT resolves to it without refreshing its attributes, so
            # `.points` can still read as of auth time. Refresh explicitly so
            # the award lands on the current balance.
            await db.refresh(kid)
            before = int(kid.points or 0)
            kid.points = before + bonus
            db.add(PointTransaction(
                type=TransactionType.BONUS,
                user_id=kid.id,
                family_id=kid.family_id,
                points=bonus,
                balance_before=before,
                balance_after=kid.points,
                description="Misión semanal lograda" if lang == "es" else "Weekly quest completed",
            ))
        await db.commit()
        await db.refresh(quest)

    @staticmethod
    def _response(
        current: Optional[WeeklyQuest], previous: Optional[WeeklyQuest], stats: WeekStats,
        today: date, gig_term: str,
    ) -> QuestResponse:
        quest = None
        if current is not None:
            target = int(current.target)
            paid = current.rewarded_at is not None
            quest = QuestProgress(
                id=current.id,
                quest=current.quest,
                target=target,
                # Once paid the bar stays full even if a later correction lowers the count.
                progress=target if paid else min(int(stats.done.get(current.quest, 0)), target),
                bonus_points=int(current.bonus_points),
                week_start=current.week_start,
                days_left=7 - today.weekday(),
                completed=paid,
            )
        celebrate = None
        for q, last_week in ((previous, True), (current, False)):     # last week's result first
            if q is not None and q.rewarded_at is not None and q.seen_at is None:
                celebrate = QuestCelebrate(
                    id=q.id, quest=q.quest, target=int(q.target),
                    bonus_points=int(q.bonus_points), last_week=last_week,
                )
                break
        return QuestResponse(applies=True, gig_term=gig_term, quest=quest, celebrate=celebrate)

    @staticmethod
    async def sync(db: AsyncSession, user: User) -> QuestResponse:
        """This week's quest for the kid: create it if missing (and something
        qualifies), pay the bonus if the goal is reached — for this week's
        quest and last week's — and return progress + any unseen result.
        This is a read endpoint that writes; both writes are idempotent."""
        if user.role not in KID_ROLES:
            return QuestResponse(applies=False)
        family_id, user_id, role = user.family_id, user.id, user.role
        star_mode = bool(user.star_mode)
        lang = "es" if (user.preferred_lang or "es").lower().startswith("es") else "en"
        fam = (await db.execute(
            select(Family.quest_bonus_points, Family.enabled_modules, Family.gig_term)
            .where(Family.id == family_id)
        )).first()
        bonus = int(fam.quest_bonus_points or 0) if fam else 0
        if bonus <= 0:
            return QuestResponse(applies=False)

        today, tz = await ProgressService.family_today(db, family_id)
        week_start = week_monday(today)
        last_week = week_start - timedelta(days=7)
        rows = await QuestService._rows(db, family_id, user_id, [week_start, last_week])
        stats = await QuestService.stats_for(db, family_id, user_id, week_start, tz, today)

        current = rows.get(week_start)
        if current is None:
            picked = pick_quest(
                rotation(week_start, user_id),
                stats,
                await QuestService._history(db, family_id, user_id, week_start, tz, today),
                await QuestService._open_gigs(db, family_id, user_id, role, star_mode, fam.enabled_modules),
            )
            if picked is not None:
                key, target = picked
                await db.execute(
                    pg_insert(WeeklyQuest)
                    .values(
                        id=uuid4(), family_id=family_id, user_id=user_id, week_start=week_start,
                        quest=key, target=target, bonus_points=bonus,
                        created_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_nothing(constraint="uq_weekly_quests_family_user_week")
                )
                await db.commit()
                current = (await QuestService._rows(db, family_id, user_id, [week_start])).get(week_start)

        if (
            current is not None and current.rewarded_at is None
            and stats.done.get(current.quest, 0) >= current.target
        ):
            await QuestService._settle(db, current, lang)

        previous = rows.get(last_week)
        if previous is not None and previous.rewarded_at is None:
            before = await QuestService.stats_for(db, family_id, user_id, last_week, tz, today)
            if before.done.get(previous.quest, 0) >= previous.target:
                await QuestService._settle(db, previous, lang)

        return QuestService._response(current, previous, stats, today, str(fam.gig_term or "gig"))

    @staticmethod
    async def ack(db: AsyncSession, user: User, quest_id: UUID) -> None:
        """Mark a paid quest's done moment as seen. Scoped to the caller's own
        rows; anyone else's id is ignored without an error."""
        await db.execute(
            update(WeeklyQuest)
            .where(
                WeeklyQuest.id == quest_id,
                WeeklyQuest.user_id == user.id,
                WeeklyQuest.family_id == user.family_id,
                WeeklyQuest.rewarded_at.is_not(None),
                WeeklyQuest.seen_at.is_(None),
            )
            .values(seen_at=datetime.now(timezone.utc))
        )
        await db.commit()

    @staticmethod
    async def hub_progress(
        db: AsyncSession, family_id: UUID, kid_ids: list[UUID],
    ) -> dict[UUID, tuple[int, int, bool]]:
        """(progress, target, done) per kid who has a quest this week, for the
        parent hub. Read-only: it never creates a quest and never pays."""
        bonus = (await db.execute(select(Family.quest_bonus_points).where(Family.id == family_id))).scalar()
        if not kid_ids or int(bonus or 0) <= 0:
            return {}
        today, tz = await ProgressService.family_today(db, family_id)
        week_start = week_monday(today)
        quests = (await db.execute(
            select(WeeklyQuest).where(
                WeeklyQuest.family_id == family_id,
                WeeklyQuest.week_start == week_start,
                WeeklyQuest.user_id.in_(kid_ids),
            )
        )).scalars().all()
        out: dict[UUID, tuple[int, int, bool]] = {}
        for q in quests:
            target = int(q.target)
            if q.rewarded_at is not None:
                out[q.user_id] = (target, target, True)
                continue
            stats = await QuestService.stats_for(db, family_id, q.user_id, week_start, tz, today)
            out[q.user_id] = (min(int(stats.done.get(q.quest, 0)), target), target, False)
        return out
