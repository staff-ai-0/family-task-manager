"""DM service (W9.3)."""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.dm import DMMessage, DMThread
from app.models.user import User


class DMService:
    @staticmethod
    async def list_threads_for_user(
        db: AsyncSession, user_id: UUID, family_id: UUID
    ) -> List[DMThread]:
        # JSONB contains check: participant_ids @> [user_id]
        q = (
            select(DMThread)
            .where(DMThread.family_id == family_id)
            .where(DMThread.participant_ids.op("@>")([str(user_id)]))
            .order_by(DMThread.updated_at.desc())
        )
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def create_thread(
        db: AsyncSession,
        family_id: UUID,
        creator_id: UUID,
        participant_ids: list[UUID],
    ) -> DMThread:
        ids = {str(creator_id)} | {str(p) for p in participant_ids}
        if len(ids) < 2:
            raise ValidationException("Thread needs at least 2 participants")

        # Verify all participants belong to the same family.
        users_q = select(User.id).where(
            and_(User.family_id == family_id, User.id.in_([UUID(i) for i in ids]))
        )
        found = {str(u) for u in (await db.execute(users_q)).scalars().all()}
        if found != ids:
            raise ForbiddenException("Some participants not in this family")

        # Dedup by participant set: if a thread with the same set already
        # exists, return it instead of creating a duplicate.
        sorted_ids = sorted(ids)
        existing_q = (
            select(DMThread)
            .where(DMThread.family_id == family_id)
            .where(DMThread.participant_ids.op("@>")(sorted_ids))
        )
        for t in (await db.execute(existing_q)).scalars().all():
            if sorted(t.participant_ids) == sorted_ids:
                return t

        t = DMThread(family_id=family_id, participant_ids=sorted_ids)
        db.add(t)
        await db.commit()
        await db.refresh(t)
        return t

    @staticmethod
    async def _get_thread_for_user(
        db: AsyncSession, thread_id: UUID, user_id: UUID, family_id: UUID
    ) -> DMThread:
        q = select(DMThread).where(
            and_(DMThread.id == thread_id, DMThread.family_id == family_id)
        )
        t = (await db.execute(q)).scalar_one_or_none()
        if not t:
            raise NotFoundException("Thread not found")
        if str(user_id) not in (t.participant_ids or []):
            raise ForbiddenException("Not a participant")
        return t

    @staticmethod
    async def list_messages(
        db: AsyncSession,
        thread_id: UUID,
        user_id: UUID,
        family_id: UUID,
        *,
        limit: int = 50,
    ) -> List[DMMessage]:
        await DMService._get_thread_for_user(db, thread_id, user_id, family_id)
        q = (
            select(DMMessage)
            .where(DMMessage.thread_id == thread_id)
            .order_by(DMMessage.created_at.desc())
            .limit(limit)
        )
        rows = list((await db.execute(q)).scalars().all())
        rows.reverse()
        return rows

    @staticmethod
    async def post_message(
        db: AsyncSession,
        thread_id: UUID,
        user_id: UUID,
        family_id: UUID,
        body: str,
    ) -> DMMessage:
        body = (body or "").strip()
        if not body:
            raise ValidationException("Empty message")
        if len(body) > 2000:
            raise ValidationException("Message too long")
        t = await DMService._get_thread_for_user(db, thread_id, user_id, family_id)
        m = DMMessage(thread_id=thread_id, sender_id=user_id, body=body)
        db.add(m)
        t.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(m)

        # Notify other participants
        try:
            from app.models.notification import NotificationType
            from app.services.notification_service import NotificationService
            sender = (
                await db.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            sender_name = sender.name if sender else "DM"
            preview = body if len(body) <= 80 else body[:77] + "…"
            for pid_str in t.participant_ids:
                pid = UUID(pid_str)
                if pid == user_id:
                    continue
                await NotificationService.create(
                    db,
                    family_id=family_id,
                    user_id=pid,
                    type=NotificationType.SHOPPING_ITEM_ADDED,
                    title=f"✉️ {sender_name}",
                    body=preview,
                    link=f"/dm/{thread_id}",
                )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("DM notif fanout failed")
        return m
