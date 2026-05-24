"""Notification service (W3.2)."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.notification import Notification


class NotificationService:
    @staticmethod
    async def create(
        db: AsyncSession,
        family_id: UUID,
        type: str,
        title: str,
        body: Optional[str] = None,
        link: Optional[str] = None,
        user_id: Optional[UUID] = None,
        expires_at: Optional[datetime] = None,
        push: bool = True,
    ) -> Notification:
        """Create a notification. user_id=None broadcasts to whole family.

        When ``push`` is True and ``user_id`` is set, fires a web-push
        message after the commit so the kid's device buzzes immediately.
        Failures in push are swallowed — the in-app feed entry is what
        matters; push is a nice-to-have.
        """
        n = Notification(
            family_id=family_id,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
            expires_at=expires_at,
        )
        db.add(n)
        await db.commit()
        await db.refresh(n)

        if push and user_id is not None:
            # Rate limit: skip push (but keep in-app feed entry) when
            # this user has already received many notifications in the
            # last 60 minutes. Saves the family from a buzzing device.
            try:
                recent = await NotificationService._recent_count(
                    db, user_id, minutes=60
                )
            except Exception:
                recent = 0
            if recent <= 10:
                try:
                    from app.services.push_service import PushService
                    await PushService.send_to_user(
                        db,
                        user_id,
                        {
                            "title": title,
                            "body": body or "",
                            "url": link or "/notifications",
                        },
                    )
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception(
                        "push fan-out failed for notification %s", n.id
                    )
        return n

    @staticmethod
    async def _recent_count(
        db: AsyncSession, user_id: UUID, minutes: int = 60
    ) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        q = (
            select(func.count())
            .select_from(Notification)
            .where(
                and_(
                    Notification.user_id == user_id,
                    Notification.created_at >= cutoff,
                )
            )
        )
        return int((await db.execute(q)).scalar() or 0)

    @staticmethod
    async def create_no_commit(
        db: AsyncSession,
        family_id: UUID,
        type: str,
        title: str,
        body: Optional[str] = None,
        link: Optional[str] = None,
        user_id: Optional[UUID] = None,
    ) -> Notification:
        """Same as create() but defers commit so callers can batch in their own txn."""
        n = Notification(
            family_id=family_id,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
        )
        db.add(n)
        return n

    @staticmethod
    async def list_for_user(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        only_unread: bool = False,
        limit: int = 50,
    ) -> List[Notification]:
        now = datetime.now(timezone.utc)
        q = (
            select(Notification)
            .where(
                and_(
                    Notification.family_id == family_id,
                    or_(
                        Notification.user_id == user_id,
                        Notification.user_id.is_(None),
                    ),
                    or_(
                        Notification.expires_at.is_(None),
                        Notification.expires_at > now,
                    ),
                )
            )
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        if only_unread:
            q = q.where(Notification.is_read.is_(False))
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def unread_count(
        db: AsyncSession, user_id: UUID, family_id: UUID
    ) -> int:
        now = datetime.now(timezone.utc)
        q = (
            select(func.count())
            .select_from(Notification)
            .where(
                and_(
                    Notification.family_id == family_id,
                    or_(
                        Notification.user_id == user_id,
                        Notification.user_id.is_(None),
                    ),
                    Notification.is_read.is_(False),
                    or_(
                        Notification.expires_at.is_(None),
                        Notification.expires_at > now,
                    ),
                )
            )
        )
        return int((await db.execute(q)).scalar() or 0)

    @staticmethod
    async def mark_read(
        db: AsyncSession,
        notif_id: UUID,
        user_id: UUID,
        family_id: UUID,
    ) -> Notification:
        q = select(Notification).where(
            and_(
                Notification.id == notif_id,
                Notification.family_id == family_id,
                or_(
                    Notification.user_id == user_id,
                    Notification.user_id.is_(None),
                ),
            )
        )
        n = (await db.execute(q)).scalar_one_or_none()
        if not n:
            raise NotFoundException("Notification not found")
        n.is_read = True
        n.read_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(n)
        return n

    @staticmethod
    async def mark_all_read(
        db: AsyncSession, user_id: UUID, family_id: UUID
    ) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            sql_update(Notification)
            .where(
                and_(
                    Notification.family_id == family_id,
                    or_(
                        Notification.user_id == user_id,
                        Notification.user_id.is_(None),
                    ),
                    Notification.is_read.is_(False),
                )
            )
            .values(is_read=True, read_at=now)
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount or 0
