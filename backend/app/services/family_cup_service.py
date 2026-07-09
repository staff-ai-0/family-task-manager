"""Family Cup + cooperative boss battle (P2).

Two cooperative, gamified views built entirely on the existing POINTS ledger
(``point_transactions``) and the task-assignment pipeline — NO pet, NO cash, no
new economy.

FAMILY CUP
    A weekly season leaderboard of POINTS earned per member in the current
    Mon-Sun window (family-local week). Resets every Monday. The ranking is a
    family-scoped SUM over ``point_transactions`` inside the window; family
    isolation is enforced by scoping to the family's member ids (the ledger has
    no family_id column). Past seasons can be persisted to ``family_cup_seasons``
    when a season is closed.

COOPERATIVE BOSS BATTLE
    A weekly family "boss" (e.g. "Monstruo del Desorden") whose max HP is the
    sum of the family's assigned MANDATORY task points for the week. Every task
    that reaches a done-and-not-rejected state deals its point value in damage,
    reducing the boss HP. It is COOPERATIVE: a missed / overdue task simply
    leaves HP on the board — it NEVER damages or penalizes the member who missed
    it. At worst the boss survives the week. HP can never go below zero.

Both are timezone-bucketed on the family's local week, mirroring the weekly
windows used across the app (kiosk snapshot, task shuffle, analytics).
"""

from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.models.family_cup import FamilyCupSeason
from app.models.point_transaction import PointTransaction
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import TaskTemplate
from app.models.user import User


# Deterministic weekly boss rotation (bilingual + emoji). Flavour only — the
# boss is always cooperative and never punishes a member.
BOSSES = [
    {"key": "mess_monster", "es": "Monstruo del Desorden",
     "en": "The Mess Monster", "emoji": "\U0001F479"},
    {"key": "dust_dragon", "es": "Dragón del Polvo",
     "en": "The Dust Dragon", "emoji": "\U0001F409"},
    {"key": "dish_ogre", "es": "Ogro de los Platos Sucios",
     "en": "The Dirty-Dishes Ogre", "emoji": "\U0001F37D️"},
    {"key": "chaos_gremlin", "es": "Gremlin del Caos",
     "en": "The Chaos Gremlin", "emoji": "\U0001F47A"},
    {"key": "laundry_kraken", "es": "Kraken de la Ropa Sucia",
     "en": "The Laundry Kraken", "emoji": "\U0001F991"},
    {"key": "clutter_troll", "es": "Trol del Tiradero",
     "en": "The Clutter Troll", "emoji": "\U0001F480"},
]

# Damage counts once a task reaches COMPLETED with an approval outcome that is
# not "still pending review" and not "rejected". Mandatory silent completions
# carry approval_status = NONE; approved gigs / proof-chores carry APPROVED.
_DAMAGE_APPROVALS = [ApprovalStatus.NONE, ApprovalStatus.APPROVED]


class FamilyCupService:
    # ─── Week / timezone helpers ─────────────────────────────────────

    @staticmethod
    async def _family_tz(db: AsyncSession, family_id: UUID) -> ZoneInfo:
        family = await db.get(Family, family_id)
        tz_name = (family.timezone if family and family.timezone else None) or "UTC"
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return ZoneInfo("UTC")

    @staticmethod
    def _week_monday(d: date) -> date:
        return d - timedelta(days=d.weekday())

    @staticmethod
    async def _resolve_week(
        db: AsyncSession, family_id: UUID, week_of: Optional[date]
    ) -> tuple[date, ZoneInfo]:
        """Return (week_start Monday, family tz). ``week_of`` pins a specific
        week (any date within it); None → the family's current local week."""
        tz = await FamilyCupService._family_tz(db, family_id)
        anchor = week_of or datetime.now(tz).date()
        return FamilyCupService._week_monday(anchor), tz

    @staticmethod
    def _boss_for_week(week_start: date) -> dict:
        idx = (week_start.toordinal() // 7) % len(BOSSES)
        return BOSSES[idx]

    # ─── Family Cup leaderboard ──────────────────────────────────────

    @staticmethod
    async def weekly_leaderboard(
        db: AsyncSession,
        family_id: UUID,
        *,
        week_of: Optional[date] = None,
    ) -> dict:
        """Points earned per member in the given family-local Mon-Sun window.

        Family isolation: point_transactions has no family_id, so the window SUM
        is scoped to THIS family's member ids — another family's ledger can never
        leak in. Only positive transactions count (redemptions/penalties don't
        subtract from a cup standing). The top scorer (points > 0) is the winner.
        """
        week_start, tz = await FamilyCupService._resolve_week(
            db, family_id, week_of
        )
        week_start_dt = datetime.combine(
            week_start, datetime.min.time(), tzinfo=tz
        )
        week_end_dt = week_start_dt + timedelta(days=7)

        members = list(
            (
                await db.execute(
                    select(User).where(
                        and_(
                            User.family_id == family_id,
                            User.is_active.is_(True),
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        user_ids = [m.id for m in members]

        points_by_user: dict = {}
        if user_ids:
            lb_q = (
                select(
                    PointTransaction.user_id,
                    func.sum(PointTransaction.points).label("pts"),
                )
                .where(
                    and_(
                        PointTransaction.user_id.in_(user_ids),
                        PointTransaction.points > 0,
                        PointTransaction.created_at >= week_start_dt,
                        PointTransaction.created_at < week_end_dt,
                    )
                )
                .group_by(PointTransaction.user_id)
            )
            points_by_user = {
                row[0]: int(row[1] or 0)
                for row in (await db.execute(lb_q)).all()
            }

        entries: List[dict] = []
        for m in members:
            role = m.role.value if hasattr(m.role, "value") else str(m.role)
            pts = points_by_user.get(m.id, 0)
            # Kids are the competitors; a parent appears only if they actually
            # earned points this week (they usually don't complete chores).
            if role == "parent" and pts <= 0:
                continue
            entries.append(
                {
                    "user_id": m.id,
                    "name": m.name,
                    "role": role,
                    "points": pts,
                }
            )

        entries.sort(key=lambda e: (-e["points"], e["name"].lower()))
        winner_id = (
            entries[0]["user_id"]
            if entries and entries[0]["points"] > 0
            else None
        )
        for e in entries:
            e["is_winner"] = e["user_id"] == winner_id

        return {
            "week_start": week_start,
            "entries": entries,
            "winner_user_id": winner_id,
        }

    # ─── Cooperative boss battle ─────────────────────────────────────

    @staticmethod
    async def boss_battle(
        db: AsyncSession,
        family_id: UUID,
        *,
        week_of: Optional[date] = None,
    ) -> dict:
        """The week's cooperative boss.

        max_hp = Σ points of the family's assigned MANDATORY (non-bonus) tasks
                 for the week (excludes CANCELLED — a parent-waived chore is not
                 part of the fight).
        damage = Σ points of those tasks that are COMPLETED and not
                 pending/rejected. Damage is clamped to max_hp so HP never goes
                 negative. Missed/overdue tasks contribute 0 damage — they are
                 never counted against the family or any member.
        """
        week_start, _tz = await FamilyCupService._resolve_week(
            db, family_id, week_of
        )

        base_where = and_(
            TaskAssignment.family_id == family_id,
            TaskAssignment.week_of == week_start,
            TaskTemplate.is_bonus.is_(False),
        )

        max_hp = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(TaskTemplate.points), 0))
                    .select_from(TaskAssignment)
                    .join(
                        TaskTemplate,
                        TaskTemplate.id == TaskAssignment.template_id,
                    )
                    .where(
                        and_(
                            base_where,
                            TaskAssignment.status != AssignmentStatus.CANCELLED,
                        )
                    )
                )
            ).scalar()
            or 0
        )

        damage = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(TaskTemplate.points), 0))
                    .select_from(TaskAssignment)
                    .join(
                        TaskTemplate,
                        TaskTemplate.id == TaskAssignment.template_id,
                    )
                    .where(
                        and_(
                            base_where,
                            TaskAssignment.status
                            == AssignmentStatus.COMPLETED,
                            TaskAssignment.approval_status.in_(
                                _DAMAGE_APPROVALS
                            ),
                        )
                    )
                )
            ).scalar()
            or 0
        )

        damage = min(damage, max_hp)
        current_hp = max(0, max_hp - damage)
        boss = FamilyCupService._boss_for_week(week_start)
        percent = int(round(damage / max_hp * 100)) if max_hp > 0 else 0

        return {
            "week_start": week_start,
            "key": boss["key"],
            "name_es": boss["es"],
            "name_en": boss["en"],
            "emoji": boss["emoji"],
            "max_hp": max_hp,
            "current_hp": current_hp,
            "damage": damage,
            "percent_defeated": percent,
            "defeated": max_hp > 0 and current_hp == 0,
            # No mandatory tasks assigned yet → nothing to fight this week.
            "active": max_hp > 0,
        }

    # ─── Combined summary (one round-trip for the UI) ────────────────

    @staticmethod
    async def summary(
        db: AsyncSession,
        family_id: UUID,
        *,
        week_of: Optional[date] = None,
    ) -> dict:
        lb = await FamilyCupService.weekly_leaderboard(
            db, family_id, week_of=week_of
        )
        boss = await FamilyCupService.boss_battle(
            db, family_id, week_of=week_of
        )
        return {
            "week_start": lb["week_start"].isoformat(),
            "leaderboard": [
                {
                    "user_id": str(e["user_id"]),
                    "name": e["name"],
                    "role": e["role"],
                    "points": e["points"],
                    "is_winner": e["is_winner"],
                }
                for e in lb["entries"]
            ],
            "winner_user_id": (
                str(lb["winner_user_id"]) if lb["winner_user_id"] else None
            ),
            "boss": {**boss, "week_start": boss["week_start"].isoformat()},
        }

    # ─── Season persistence (history) ────────────────────────────────

    @staticmethod
    async def record_season_winner(
        db: AsyncSession,
        family_id: UUID,
        *,
        week_of: date,
    ) -> dict:
        """Upsert the winner of the given week's season into family_cup_seasons.

        Idempotent per (family, week) via the unique constraint — re-running
        refreshes the stored winner/points. Returns the persisted snapshot.
        """
        lb = await FamilyCupService.weekly_leaderboard(
            db, family_id, week_of=week_of
        )
        week_start = lb["week_start"]
        winner_id = lb["winner_user_id"]
        winner_name = None
        winner_points = 0
        if winner_id is not None:
            top = next(
                e for e in lb["entries"] if e["user_id"] == winner_id
            )
            winner_name = top["name"]
            winner_points = top["points"]

        stmt = (
            pg_insert(FamilyCupSeason)
            .values(
                family_id=family_id,
                week_start=week_start,
                winner_user_id=winner_id,
                winner_name=winner_name,
                winner_points=winner_points,
            )
            .on_conflict_do_update(
                index_elements=["family_id", "week_start"],
                set_={
                    "winner_user_id": winner_id,
                    "winner_name": winner_name,
                    "winner_points": winner_points,
                },
            )
        )
        await db.execute(stmt)
        await db.commit()
        return {
            "week_start": week_start.isoformat(),
            "winner_user_id": str(winner_id) if winner_id else None,
            "winner_name": winner_name,
            "winner_points": winner_points,
        }

    @staticmethod
    async def close_previous_season(
        db: AsyncSession, family_id: UUID
    ) -> dict:
        """Finalize LAST week's season (the just-ended Mon-Sun window)."""
        tz = await FamilyCupService._family_tz(db, family_id)
        last_week_anchor = datetime.now(tz).date() - timedelta(days=7)
        return await FamilyCupService.record_season_winner(
            db, family_id, week_of=last_week_anchor
        )

    @staticmethod
    async def list_past_seasons(
        db: AsyncSession, family_id: UUID, *, limit: int = 12
    ) -> List[dict]:
        rows = list(
            (
                await db.execute(
                    select(FamilyCupSeason)
                    .where(FamilyCupSeason.family_id == family_id)
                    .order_by(FamilyCupSeason.week_start.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "week_start": r.week_start.isoformat(),
                "winner_user_id": (
                    str(r.winner_user_id) if r.winner_user_id else None
                ),
                "winner_name": r.winner_name,
                "winner_points": int(r.winner_points or 0),
            }
            for r in rows
        ]
