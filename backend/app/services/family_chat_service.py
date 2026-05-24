"""Family chat service (W8.1 + W8.3)."""

import asyncio
import json
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.models.family_chat import FamilyChatMessage
from app.models.user import User


# SSE tuning. Total stream lifetime per HTTP request; client reconnects
# after. Poll interval determines latency on new messages.
STREAM_WINDOW_SECONDS = 30
STREAM_POLL_SECONDS = 2.0


class FamilyChatService:
    # ─── Reactions (W8.6) ────────────────────────────────────────────

    @staticmethod
    async def add_reaction(
        db: AsyncSession,
        message_id: UUID,
        user_id: UUID,
        family_id: UUID,
        emoji: str,
    ):
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from app.models.family_chat_reaction import FamilyChatReaction

        emoji = (emoji or "").strip()
        if not emoji or len(emoji) > 16:
            raise ValidationException("emoji must be 1-16 chars")
        msg_q = select(FamilyChatMessage).where(
            and_(
                FamilyChatMessage.id == message_id,
                FamilyChatMessage.family_id == family_id,
            )
        )
        if (await db.execute(msg_q)).scalar_one_or_none() is None:
            raise ValidationException("Message not found in family")

        stmt = (
            pg_insert(FamilyChatReaction)
            .values(message_id=message_id, user_id=user_id, emoji=emoji)
            .on_conflict_do_nothing(
                index_elements=["message_id", "user_id", "emoji"]
            )
        )
        await db.execute(stmt)
        await db.commit()

    @staticmethod
    async def remove_reaction(
        db: AsyncSession,
        message_id: UUID,
        user_id: UUID,
        family_id: UUID,
        emoji: str,
    ):
        from sqlalchemy import delete as sql_delete
        from app.models.family_chat_reaction import FamilyChatReaction

        msg_q = select(FamilyChatMessage).where(
            and_(
                FamilyChatMessage.id == message_id,
                FamilyChatMessage.family_id == family_id,
            )
        )
        if (await db.execute(msg_q)).scalar_one_or_none() is None:
            raise ValidationException("Message not found in family")

        await db.execute(
            sql_delete(FamilyChatReaction).where(
                and_(
                    FamilyChatReaction.message_id == message_id,
                    FamilyChatReaction.user_id == user_id,
                    FamilyChatReaction.emoji == emoji,
                )
            )
        )
        await db.commit()

    @staticmethod
    async def reactions_for_messages(
        db: AsyncSession, message_ids: list
    ) -> dict:
        from app.models.family_chat_reaction import FamilyChatReaction
        if not message_ids:
            return {}
        q = select(FamilyChatReaction).where(
            FamilyChatReaction.message_id.in_(message_ids)
        )
        rows = list((await db.execute(q)).scalars().all())
        bucket: dict = {}
        for r in rows:
            key = (r.message_id, r.emoji)
            bucket.setdefault(key, []).append(r.user_id)
        out: dict = {mid: [] for mid in message_ids}
        for (mid, emoji), users in bucket.items():
            out[mid].append({
                "emoji": emoji,
                "count": len(users),
                "user_ids": [str(u) for u in users],
            })
        return out

    # ─── Messages ────────────────────────────────────────────────────

    @staticmethod
    async def list_messages(
        db: AsyncSession,
        family_id: UUID,
        *,
        limit: int = 50,
        before_id: UUID | None = None,
    ) -> List[FamilyChatMessage]:
        q = (
            select(FamilyChatMessage)
            .where(FamilyChatMessage.family_id == family_id)
        )
        if before_id is not None:
            anchor_q = select(FamilyChatMessage.created_at).where(
                FamilyChatMessage.id == before_id
            )
            anchor = (await db.execute(anchor_q)).scalar_one_or_none()
            if anchor is not None:
                q = q.where(FamilyChatMessage.created_at < anchor)
        q = q.order_by(FamilyChatMessage.created_at.desc()).limit(limit)
        rows = list((await db.execute(q)).scalars().all())
        rows.reverse()
        return rows

    @staticmethod
    async def post_message(
        db: AsyncSession,
        family_id: UUID,
        sender_id: UUID,
        body: str,
    ) -> FamilyChatMessage:
        body = (body or "").strip()
        if not body:
            raise ValidationException("Empty message")
        if len(body) > 2000:
            raise ValidationException("Message too long (max 2000 chars)")

        msg = FamilyChatMessage(
            family_id=family_id,
            sender_id=sender_id,
            body=body,
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)

        # Notify everyone in the family except the sender.
        await FamilyChatService._fanout_notification(
            db, family_id, sender_id, body
        )
        return msg

    @staticmethod
    async def unread_count(
        db: AsyncSession, user_id: UUID, family_id: UUID
    ) -> int:
        from sqlalchemy import func as sa_func
        u = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if not u:
            return 0
        cutoff = u.chat_last_read_at
        q = (
            select(sa_func.count())
            .select_from(FamilyChatMessage)
            .where(FamilyChatMessage.family_id == family_id)
            .where(FamilyChatMessage.sender_id != user_id)
        )
        if cutoff is not None:
            q = q.where(FamilyChatMessage.created_at > cutoff)
        return int((await db.execute(q)).scalar() or 0)

    @staticmethod
    async def mark_read(
        db: AsyncSession, user_id: UUID
    ) -> None:
        u = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if not u:
            return
        u.chat_last_read_at = datetime.now(timezone.utc)
        await db.commit()

    @staticmethod
    async def stream_messages(
        db: AsyncSession,
        family_id: UUID,
        after_ts: Optional[datetime] = None,
    ):
        """SSE generator. Emits `event: message` for each new message that
        appears after ``after_ts`` (default: now). Closes after
        ``STREAM_WINDOW_SECONDS`` so the client reconnects. Heartbeats
        every ~10s so proxies don't time out.
        """
        cursor = after_ts or datetime.now(timezone.utc)
        elapsed = 0.0
        last_heartbeat = 0.0

        while elapsed < STREAM_WINDOW_SECONDS:
            q = (
                select(FamilyChatMessage)
                .where(
                    and_(
                        FamilyChatMessage.family_id == family_id,
                        FamilyChatMessage.created_at > cursor,
                    )
                )
                .order_by(FamilyChatMessage.created_at.asc())
                .limit(50)
            )
            rows = list((await db.execute(q)).scalars().all())
            for m in rows:
                payload = {
                    "id": str(m.id),
                    "sender_id": str(m.sender_id) if m.sender_id else None,
                    "body": m.body,
                    "created_at": m.created_at.isoformat(),
                }
                yield "event: message\ndata: " + json.dumps(payload) + "\n\n"
                cursor = m.created_at

            await asyncio.sleep(STREAM_POLL_SECONDS)
            elapsed += STREAM_POLL_SECONDS
            last_heartbeat += STREAM_POLL_SECONDS
            if last_heartbeat >= 10:
                last_heartbeat = 0
                yield ": heartbeat\n\n"

        yield "event: done\ndata: {}\n\n"

    @staticmethod
    async def _fanout_notification(
        db: AsyncSession,
        family_id: UUID,
        sender_id: UUID,
        body: str,
    ) -> None:
        """Best-effort in-app + push fan-out. Swallow failures."""
        from app.models.notification import NotificationType
        from app.services.notification_service import NotificationService

        sender = (
            await db.execute(select(User).where(User.id == sender_id))
        ).scalar_one_or_none()
        sender_name = sender.name if sender else "Family"

        recipients_q = (
            select(User.id)
            .where(User.family_id == family_id)
            .where(User.is_active.is_(True))
            .where(User.id != sender_id)
        )
        recipients = (await db.execute(recipients_q)).scalars().all()

        preview = body if len(body) <= 80 else body[:77] + "…"
        for uid in recipients:
            try:
                await NotificationService.create(
                    db,
                    family_id=family_id,
                    user_id=uid,
                    type=NotificationType.SHOPPING_ITEM_ADDED,  # generic bucket
                    title=f"💬 {sender_name}",
                    body=preview,
                    link="/chat",
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "family chat notification failed for user %s", uid
                )
