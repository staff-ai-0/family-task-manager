"""UX-D4b mystery box: a perfect day earns a closed box; opening it reveals a
surprise from the parents' jar, or a points bonus when the jar is empty.

Created on read (the badge/quest pattern) and paid once at opening through a
guarded UPDATE. Pure rules first, then the family-scoped queries.
"""
from __future__ import annotations

import random
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationError
from app.models.family import Family
from app.models.mystery import MysteryBox, MysterySurprise
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.user import User
from app.schemas.progress import DeliveryView, MysteryBoxView, MysteryResponse
from app.services.points_service import PointsService
from app.services.progress_service import KID_ROLES, DayState, ProgressService

JAR_MAX = 20      # surprises per family
TITLE_MAX = 60
EMOJI_MAX = 4


class MysteryBoxesOff(Exception):
    """The family's boxes are off (0 or undecided): the box waits, unopened."""


def points_for(max_points: int, rng: random.Random) -> int:
    """A whole number from a quarter of the maximum up to the maximum, never 0."""
    m = max(1, int(max_points or 0))
    return rng.randint(max(1, m // 4), m)


def pick_surprise(
    surprises: list[MysterySurprise], last_surprise_id: Optional[UUID], rng: random.Random,
) -> Optional[MysterySurprise]:
    """A random surprise, never the kid's most recent one when there is a choice."""
    if not surprises:
        return None
    pool = [s for s in surprises if s.id != last_surprise_id] or list(surprises)
    return rng.choice(pool)


def _view(box: MysteryBox) -> MysteryBoxView:
    return MysteryBoxView(
        id=box.id, day=box.day, opened=box.opened_at is not None, kind=box.kind,
        surprise_title=box.surprise_title, surprise_emoji=box.surprise_emoji, points=int(box.points or 0),
    )


# ── Queries (family-scoped) ──────────────────────────────────────────────
class MysteryService:
    @staticmethod
    async def _max_points(db: AsyncSession, family_id: UUID) -> int:
        return int((await db.execute(select(Family.mystery_box_points).where(Family.id == family_id))).scalar() or 0)

    @staticmethod
    async def sync(db: AsyncSession, user: User) -> MysteryResponse:
        """Create today's closed box when the day is perfect (idempotent), then
        report the kid's unopened boxes and today's opened one."""
        if user.role not in KID_ROLES:
            return MysteryResponse(applies=False)
        family_id, user_id = user.family_id, user.id
        maximum = await MysteryService._max_points(db, family_id)
        if maximum <= 0:
            return MysteryResponse(applies=True, enabled=False)
        today, tz = await ProgressService.family_today(db, family_id)
        # Today and yesterday only: yesterday covers a day finished away from
        # the home (pet page, parent marked it done) and first read after
        # midnight — the streak counts it, so the box must exist too. Older
        # days are not backfilled: switching a family on must not drop a
        # year of boxes at once.
        yesterday = today - timedelta(days=1)
        states = await ProgressService.day_states(db, family_id, user_id, today, tz, since=yesterday)
        perfect = [d for d in (yesterday, today) if states.get(d) == DayState.done]
        if perfect:
            now = datetime.now(timezone.utc)
            await db.execute(
                pg_insert(MysteryBox)
                .values([dict(family_id=family_id, user_id=user_id, day=d, points=0, created_at=now) for d in perfect])
                .on_conflict_do_nothing(constraint="uq_mystery_boxes_family_user_day")
            )
            await db.commit()
        # "Opened today" is about WHEN it was opened (family-local), not which
        # day earned it: a kid opening yesterday's waiting box must still see
        # what they got.
        midnight = datetime.combine(today, time.min, tzinfo=tz)
        rows = (await db.execute(
            select(MysteryBox).where(
                MysteryBox.family_id == family_id, MysteryBox.user_id == user_id,
                (MysteryBox.opened_at.is_(None)) | (MysteryBox.opened_at >= midnight),
            ).order_by(MysteryBox.day)
        )).scalars().all()
        unopened = [_view(b) for b in rows if b.opened_at is None]
        opened = [b for b in rows if b.opened_at is not None]
        opened_today = _view(max(opened, key=lambda b: b.opened_at)) if opened else None
        return MysteryResponse(applies=True, enabled=True, unopened=unopened, opened_today=opened_today)

    @staticmethod
    async def open(db: AsyncSession, user: User, box_id: UUID, rng: Optional[random.Random] = None) -> MysteryBoxView:
        """Decide and pay the box's content exactly once. The guarded UPDATE is
        the gate: of two openers, the second waits on the row lock, matches
        nothing, and reads what the first one revealed."""
        rng = rng or random.Random()
        family_id, user_id = user.family_id, user.id
        box = (await db.execute(
            select(MysteryBox).where(
                MysteryBox.id == box_id, MysteryBox.family_id == family_id, MysteryBox.user_id == user_id,
            )
        )).scalar_one_or_none()
        if box is None:
            raise NotFoundException("Box not found")
        if box.opened_at is not None:
            return _view(box)
        maximum = await MysteryService._max_points(db, family_id)
        if maximum <= 0:
            raise MysteryBoxesOff()

        jar = await MysteryService.list_surprises(db, family_id)
        last = (await db.execute(
            select(MysteryBox.surprise_id).where(
                MysteryBox.family_id == family_id, MysteryBox.user_id == user_id,
                MysteryBox.opened_at.is_not(None), MysteryBox.id != box_id,
            ).order_by(MysteryBox.opened_at.desc()).limit(1)
        )).scalar()
        surprise = pick_surprise(jar, last, rng)
        values = dict(opened_at=datetime.now(timezone.utc))
        if surprise is not None:
            values.update(kind="surprise", surprise_id=surprise.id, surprise_title=surprise.title,
                          surprise_emoji=surprise.emoji, points=0)
        else:
            values.update(kind="points", points=points_for(maximum, rng))
        opened = (await db.execute(
            update(MysteryBox)
            .where(MysteryBox.id == box_id, MysteryBox.opened_at.is_(None))
            .values(**values)
            .returning(MysteryBox.id)
            .execution_options(synchronize_session=False)
        )).first()
        if opened is not None and values["kind"] == "points":
            kid = await PointsService._get_user_locked(db, user_id, family_id)
            await db.refresh(kid)                      # identity map may hold the auth-time balance
            before = int(kid.points or 0)
            kid.points = before + values["points"]
            lang = (user.preferred_lang or "en").lower()
            db.add(PointTransaction(
                type=TransactionType.BONUS, user_id=kid.id, family_id=family_id, points=values["points"],
                balance_before=before, balance_after=kid.points,
                description="Caja sorpresa" if lang.startswith("es") else "Mystery box",
            ))
        await db.commit()
        await db.refresh(box)
        return _view(box)

    @staticmethod
    async def deliveries(db: AsyncSession, family_id: UUID) -> list[DeliveryView]:
        rows = (await db.execute(
            select(MysteryBox, User.name)
            .join(User, User.id == MysteryBox.user_id)
            .where(MysteryBox.family_id == family_id, MysteryBox.kind == "surprise", MysteryBox.delivered_at.is_(None),
                   User.deleted_at.is_(None))
            .order_by(MysteryBox.opened_at.desc())
        )).all()
        return [
            DeliveryView(id=b.id, kid_name=name, surprise_title=b.surprise_title or "", surprise_emoji=b.surprise_emoji,
                         day=b.day, opened_at=b.opened_at)
            for b, name in rows
        ]

    @staticmethod
    async def mark_delivered(db: AsyncSession, parent: User, box_id: UUID) -> None:
        done = (await db.execute(
            update(MysteryBox)
            .where(MysteryBox.id == box_id, MysteryBox.family_id == parent.family_id,
                   MysteryBox.kind == "surprise", MysteryBox.delivered_at.is_(None))
            .values(delivered_at=datetime.now(timezone.utc), delivered_by=parent.id)
            .returning(MysteryBox.id)
            .execution_options(synchronize_session=False)
        )).first()
        if done is None:
            raise NotFoundException("Nothing to deliver")
        await db.commit()

    # ── the jar ─────────────────────────────────────────────────────────
    @staticmethod
    async def list_surprises(db: AsyncSession, family_id: UUID) -> list[MysterySurprise]:
        return list((await db.execute(
            select(MysterySurprise).where(MysterySurprise.family_id == family_id).order_by(MysterySurprise.created_at)
        )).scalars().all())

    @staticmethod
    async def add_surprise(db: AsyncSession, parent: User, title: str, emoji: Optional[str]) -> MysterySurprise:
        clean = " ".join((title or "").split())
        if not clean or len(clean) > TITLE_MAX:
            raise ValidationError(f"A surprise is 1 to {TITLE_MAX} characters")
        icon = (emoji or "").strip() or None
        if icon is not None and len(icon) > EMOJI_MAX:
            raise ValidationError("One emoji at most")
        count = (await db.execute(
            select(func.count()).select_from(MysterySurprise).where(MysterySurprise.family_id == parent.family_id)
        )).scalar() or 0
        if count >= JAR_MAX:
            raise ValidationError(f"The jar holds {JAR_MAX} surprises at most")
        row = MysterySurprise(family_id=parent.family_id, title=clean, emoji=icon, created_by=parent.id,
                              created_at=datetime.now(timezone.utc))
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def remove_surprise(db: AsyncSession, family_id: UUID, surprise_id: UUID) -> None:
        row = (await db.execute(
            select(MysterySurprise).where(MysterySurprise.id == surprise_id, MysterySurprise.family_id == family_id)
        )).scalar_one_or_none()
        if row is None:
            raise NotFoundException("Surprise not found")
        await db.delete(row)
        await db.commit()
