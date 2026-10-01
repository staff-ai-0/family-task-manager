"""UX-D2 badges: 8 families × 3 tiers, earned from history and kept forever —
see docs/superpowers/specs/2026-10-01-ux-d2-badges-design.md.

Counts are derived on read (like UX-D1); only EARNED tiers are stored
(`user_badges`), so a later parent correction never takes a badge away.
Thresholds live here and nowhere else; names and emoji live only in
frontend/src/lib/badges.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modules import effective_modules
from app.models.family import Family
from app.models.family_cup import FamilyCupSeason
from app.models.gig import GigClaim, GigClaimStatus
from app.models.kid_savings_goal import KidSavingsGoal
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User
from app.models.user_badge import UserBadge
from app.schemas.progress import BadgeProgress, BadgesResponse, UnseenBadge
from app.services.family_cup_service import FamilyCupService
from app.services.progress_service import KID_ROLES, ProgressService, compute_streak


@dataclass(frozen=True)
class BadgeDef:
    thresholds: tuple[int, int, int]   # count needed for bronze, silver, gold
    module: Optional[str] = None       # togglable module this family belongs to


# Insertion order is the catalog order every surface renders.
BADGES: dict[str, BadgeDef] = {
    "chores": BadgeDef((10, 50, 200)),
    "streak": BadgeDef((7, 30, 100)),
    "perfect_week": BadgeDef((1, 4, 12)),
    "extra_mile": BadgeDef((1, 10, 50)),
    "gigs": BadgeDef((1, 10, 50), module="gigs"),
    "saver": BadgeDef((1, 3, 10), module="gigs"),
    "rewards": BadgeDef((1, 5, 20)),
    "cup": BadgeDef((1, 3, 10)),
}
MAX_TIER = 3


def tiers_for(count: int, thresholds: tuple[int, ...]) -> int:
    """How many tiers a count has reached (0..MAX_TIER)."""
    return sum(1 for threshold in thresholds if count >= threshold)


def next_target(tier: int, thresholds: tuple[int, ...]) -> Optional[int]:
    """The count needed for the tier after `tier`; None once gold is held."""
    return thresholds[tier] if 0 <= tier < len(thresholds) else None


def visible_badges(enabled_modules: Optional[Iterable[str]]) -> tuple[str, ...]:
    """Catalog keys a family sees: a family whose module is off is skipped
    (not evaluated, not returned). Stored rows are kept regardless."""
    on = effective_modules(enabled_modules)
    return tuple(key for key, badge in BADGES.items() if badge.module is None or badge.module in on)


# ── Queries (family-scoped) ──────────────────────────────────────────────
class BadgeService:
    @staticmethod
    async def visible_for(db: AsyncSession, family_id: UUID) -> tuple[str, ...]:
        enabled = (await db.execute(select(Family.enabled_modules).where(Family.id == family_id))).scalar()
        return visible_badges(enabled)

    @staticmethod
    async def _count(db: AsyncSession, model, *where) -> int:
        return int((await db.execute(select(func.count()).select_from(model).where(*where))).scalar() or 0)

    @staticmethod
    async def counts_for(
        db: AsyncSession, family_id: UUID, user_id: UUID, today: date, tz: ZoneInfo, visible: tuple[str, ...],
    ) -> dict[str, int]:
        """Current count behind each visible badge family. A hidden family is
        not evaluated at all."""
        # Chores + extra mile in one pass, all-time: completed, not graded
        # missed, and needing no review or approved — work awaiting review
        # does not count yet (a badge is permanent; a later rejection could
        # not take it back).
        # D1's streak uses the on-time variant — see ProgressService.day_states.
        done_rows = (await db.execute(
            select(TaskTemplate.is_bonus, func.count())
            .select_from(TaskAssignment)
            .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.status == AssignmentStatus.COMPLETED,
                TaskAssignment.approval_status.in_([ApprovalStatus.NONE, ApprovalStatus.APPROVED]),
                or_(TaskAssignment.completion_grade.is_(None), TaskAssignment.completion_grade != "missed"),
            )
            .group_by(TaskTemplate.is_bonus)
        )).all()
        by_bonus = {bool(is_bonus): int(n) for is_bonus, n in done_rows}
        streak = compute_streak(await ProgressService.day_states(db, family_id, user_id, today, tz), today)

        counts: dict[str, int] = {
            "chores": by_bonus.get(False, 0),
            "streak": int(streak.best),
            "perfect_week": int(streak.perfect_weeks),
            "extra_mile": by_bonus.get(True, 0),
            # reward_id IS NOT NULL: pet-shop purchases write the same
            # transaction type without a reward and must not count.
            "rewards": await BadgeService._count(
                db, PointTransaction,
                PointTransaction.family_id == family_id,
                PointTransaction.user_id == user_id,
                PointTransaction.type == TransactionType.REWARD_REDEEMED,
                PointTransaction.reward_id.is_not(None),
                PointTransaction.points < 0,
            ),
            "cup": await BadgeService._count(
                db, FamilyCupSeason,
                FamilyCupSeason.family_id == family_id,
                FamilyCupSeason.winner_user_id == user_id,
            ),
        }
        if "gigs" in visible:
            counts["gigs"] = await BadgeService._count(
                db, GigClaim,
                GigClaim.family_id == family_id,
                GigClaim.claimed_by == user_id,
                GigClaim.status == GigClaimStatus.APPROVED,
            )
        if "saver" in visible:
            counts["saver"] = await BadgeService._count(
                db, KidSavingsGoal,
                KidSavingsGoal.family_id == family_id,
                KidSavingsGoal.user_id == user_id,
                KidSavingsGoal.reached_at.is_not(None),
            )
        return {key: counts[key] for key in visible}

    @staticmethod
    async def _rows(db: AsyncSession, family_id: UUID, user_id: UUID) -> list[UserBadge]:
        return list((await db.execute(
            select(UserBadge).where(UserBadge.family_id == family_id, UserBadge.user_id == user_id)
        )).scalars().all())

    @staticmethod
    async def _award(db: AsyncSession, family_id: UUID, user_id: UUID, pairs: list[tuple[str, int]]) -> None:
        """Record earned tiers. ON CONFLICT DO NOTHING: two requests evaluating
        at the same moment (two tabs) must both succeed and award once."""
        if not pairs:
            return
        now = datetime.now(timezone.utc)
        await db.execute(
            pg_insert(UserBadge)
            .values([
                {"id": uuid4(), "family_id": family_id, "user_id": user_id,
                 "badge": badge, "tier": tier, "earned_at": now}
                for badge, tier in pairs
            ])
            .on_conflict_do_nothing(constraint="uq_user_badges_family_user_badge_tier")
        )
        await db.commit()

    @staticmethod
    def _response(visible: tuple[str, ...], counts: dict[str, int], rows: list[UserBadge]) -> BadgesResponse:
        shown = sorted(
            (r for r in rows if r.badge in visible),
            key=lambda r: (visible.index(r.badge), r.tier),
        )
        top: dict[str, UserBadge] = {}
        for row in shown:               # ascending tier, so the last one wins
            top[row.badge] = row
        badges = []
        for key in visible:
            best = top.get(key)
            tier = int(best.tier) if best else 0
            badges.append(BadgeProgress(
                badge=key,
                count=int(counts[key]),
                tier=tier,
                next_target=next_target(tier, BADGES[key].thresholds),
                earned_at=best.earned_at if best else None,
            ))
        return BadgesResponse(
            applies=True,
            badges=badges,
            unseen=[UnseenBadge(id=r.id, badge=r.badge, tier=int(r.tier)) for r in shown if r.seen_at is None],
            earned_total=len(shown),
        )

    @staticmethod
    async def _ensure_last_cup_season(db: AsyncSession, family_id: UUID, today: date) -> None:
        """Family Cup seasons are only persisted when someone closes the week.
        Record LAST week's winner if nobody did, so a kid's win counts without
        a parent tapping "close the week". Insert-if-missing only: an already
        recorded season is never touched, and older weeks are not backfilled."""
        last_monday = today - timedelta(days=today.weekday() + 7)
        recorded = (await db.execute(
            select(FamilyCupSeason.id).where(
                FamilyCupSeason.family_id == family_id,
                FamilyCupSeason.week_start == last_monday,
            )
        )).first()
        if recorded is None:
            await FamilyCupService.close_previous_season(db, family_id)

    @staticmethod
    async def sync(db: AsyncSession, user: User) -> BadgesResponse:
        """Evaluate the kid's badges, record any newly earned tier, and return
        progress + what has not been celebrated yet. Read-only once nothing
        new was earned and last week's Family Cup season is on record (see
        `_ensure_last_cup_season`). Stored tiers are never removed: `tier` in
        the response comes from the stored rows, `count` from history."""
        if user.role not in KID_ROLES:
            return BadgesResponse(applies=False)
        family_id, user_id = user.family_id, user.id
        today, tz = await ProgressService.family_today(db, family_id)
        await BadgeService._ensure_last_cup_season(db, family_id, today)
        visible = await BadgeService.visible_for(db, family_id)
        counts = await BadgeService.counts_for(db, family_id, user_id, today, tz, visible)
        rows = await BadgeService._rows(db, family_id, user_id)
        have = {(r.badge, r.tier) for r in rows}
        missing = [
            (key, tier)
            for key in visible
            for tier in range(1, tiers_for(counts[key], BADGES[key].thresholds) + 1)
            if (key, tier) not in have
        ]
        if missing:
            await BadgeService._award(db, family_id, user_id, missing)
            rows = await BadgeService._rows(db, family_id, user_id)
        return BadgeService._response(visible, counts, rows)

    @staticmethod
    async def ack(db: AsyncSession, user: User, ids: list[UUID]) -> None:
        """Mark the given tiers as celebrated. Scoped to the caller's own rows;
        ids that belong to anyone else are ignored without an error."""
        await db.execute(
            update(UserBadge)
            .where(
                UserBadge.id.in_(ids),
                UserBadge.user_id == user.id,
                UserBadge.family_id == user.family_id,
                UserBadge.seen_at.is_(None),
            )
            .values(seen_at=datetime.now(timezone.utc))
        )
        await db.commit()

    @staticmethod
    async def earned_counts(db: AsyncSession, family_id: UUID, visible: tuple[str, ...]) -> dict[UUID, int]:
        """Earned tiers per kid for the parent hub: one grouped query over
        stored rows (no evaluation on the parent's request)."""
        rows = (await db.execute(
            select(UserBadge.user_id, func.count())
            .where(UserBadge.family_id == family_id, UserBadge.badge.in_(visible))
            .group_by(UserBadge.user_id)
        )).all()
        return {user_id: int(n) for user_id, n in rows}
