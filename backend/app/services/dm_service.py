"""DM service (W9.3 + W11B SSE)."""

import json
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


# SSE tuning — see family_chat_service for the full rationale.
STREAM_WINDOW_SECONDS = 30
PUBSUB_WAIT_SECONDS = 1.0
FALLBACK_POLL_SECONDS = 15.0
HEARTBEAT_SECONDS = 10.0


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
    async def stream_messages(
        thread_id: UUID,
        user_id: UUID,
        family_id: UUID,
        after_ts: Optional[datetime] = None,
    ):
        """SSE generator — same pattern as family chat. Verifies participant.

        Delivery is event-driven: ``post_message`` PUBLISHes to a thread-scoped
        Redis channel and this generator wakes on that signal, then re-reads the
        DB (source of truth). A bounded fallback poll every
        ``FALLBACK_POLL_SECONDS`` still fires so a dropped publish can't lose a
        message; if Redis is unreachable the stream degrades to pure polling.

        Uses a FRESH short-lived session per DB read (not a request-scoped
        Depends(get_db) session) so a long-lived SSE connection never pins a
        pooled DB connection idle-in-transaction (pool exhaustion → 502s).
        """
        import time as _time

        from app.core import message_bus
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            await DMService._get_thread_for_user(s, thread_id, user_id, family_id)
        cursor = after_ts or datetime.now(timezone.utc)

        async def _drain():
            nonlocal cursor
            async with AsyncSessionLocal() as s:
                q = (
                    select(DMMessage)
                    .where(
                        and_(
                            DMMessage.thread_id == thread_id,
                            DMMessage.created_at > cursor,
                        )
                    )
                    .order_by(DMMessage.created_at.asc())
                    .limit(50)
                )
                rows = list((await s.execute(q)).scalars().all())
            chunks = []
            for m in rows:
                payload = {
                    "id": str(m.id),
                    "thread_id": str(m.thread_id),
                    "sender_id": str(m.sender_id) if m.sender_id else None,
                    "body": m.body,
                    "created_at": m.created_at.isoformat(),
                }
                chunks.append(
                    "event: message\ndata: " + json.dumps(payload) + "\n\n"
                )
                cursor = m.created_at
            return chunks

        # Cover the reconnect gap before waiting.
        for chunk in await _drain():
            yield chunk

        channel = message_bus.dm_channel(thread_id)
        pubsub = await message_bus.subscribe(channel)
        try:
            start = _time.monotonic()
            last_poll = start
            last_heartbeat = start
            while (_time.monotonic() - start) < STREAM_WINDOW_SECONDS:
                woke = await message_bus.wait_for_event(pubsub, PUBSUB_WAIT_SECONDS)
                now = _time.monotonic()
                if woke or (now - last_poll) >= FALLBACK_POLL_SECONDS:
                    last_poll = now
                    for chunk in await _drain():
                        yield chunk
                if (now - last_heartbeat) >= HEARTBEAT_SECONDS:
                    last_heartbeat = now
                    yield ": heartbeat\n\n"
        finally:
            await message_bus.close_pubsub(pubsub, channel)
        yield "event: done\ndata: {}\n\n"

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

        # Wake any live SSE stream for this thread (best-effort signal).
        from app.core import message_bus
        await message_bus.publish(
            message_bus.dm_channel(thread_id),
            {
                "id": str(m.id),
                "thread_id": str(thread_id),
                "sender_id": str(user_id) if user_id else None,
                "body": m.body,
                "created_at": m.created_at.isoformat(),
            },
        )

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
