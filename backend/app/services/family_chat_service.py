"""Family chat service (W8.1 + W8.3)."""

import json
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.models.family_chat import FamilyChatMessage
from app.models.user import User


# SSE tuning. Total stream lifetime per HTTP request; client reconnects after.
STREAM_WINDOW_SECONDS = 30
# Loop tick: how long each Redis pub/sub read blocks before we re-check the
# heartbeat/fallback/deadline cadence. Cheap local socket read, not a DB query.
PUBSUB_WAIT_SECONDS = 1.0
# Safety net: re-read the DB at least this often even with no publish, so a
# dropped pub/sub signal can't silently lose a message. Well under the reconnect
# window, and each reconnect also re-drains — so worst-case miss latency is
# bounded by this, not by the stream window.
FALLBACK_POLL_SECONDS = 15.0
# Comment-line keepalive so proxies don't idle-close the stream.
HEARTBEAT_SECONDS = 10.0


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
            # Scope the anchor lookup to this family — otherwise a foreign
            # message id leaks its timestamp as a pagination cutoff (timing
            # oracle).
            anchor_q = select(FamilyChatMessage.created_at).where(
                FamilyChatMessage.id == before_id,
                FamilyChatMessage.family_id == family_id,
            )
            anchor = (await db.execute(anchor_q)).scalar_one_or_none()
            if anchor is not None:
                q = q.where(FamilyChatMessage.created_at < anchor)
        q = q.order_by(FamilyChatMessage.created_at.desc()).limit(limit)
        rows = list((await db.execute(q)).scalars().all())
        rows.reverse()
        return rows

    @staticmethod
    async def _get_family_message(
        db: AsyncSession, message_id: UUID, family_id: UUID
    ) -> FamilyChatMessage:
        """Message by id, scoped to the family (404 outside it)."""
        from app.core.exceptions import NotFoundException

        row = (await db.execute(
            select(FamilyChatMessage).where(
                FamilyChatMessage.id == message_id,
                FamilyChatMessage.family_id == family_id,
            )
        )).scalar_one_or_none()
        if row is None:
            raise NotFoundException("Message not found")
        return row

    @staticmethod
    async def edit_message(
        db: AsyncSession,
        message_id: UUID,
        family_id: UUID,
        body: str,
    ) -> FamilyChatMessage:
        """Parent moderation: rewrite a message's body (stamps edited_at).

        Role enforcement lives at the route (require_parent_role); this
        service call only guarantees family scoping.
        """
        body = (body or "").strip()
        if not body:
            raise ValidationException("Empty message")
        msg = await FamilyChatService._get_family_message(
            db, message_id, family_id
        )
        msg.body = body
        msg.edited_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(msg)
        return msg

    @staticmethod
    async def delete_message(
        db: AsyncSession, message_id: UUID, family_id: UUID
    ) -> None:
        """Parent moderation: remove a message (reactions cascade)."""
        msg = await FamilyChatService._get_family_message(
            db, message_id, family_id
        )
        await db.delete(msg)
        await db.commit()

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

        # Wake any live SSE stream for this family (best-effort). Payload is only
        # a signal — subscribers re-read the DB — but we send the full row so it
        # stays useful for future direct-consume callers.
        from app.core import message_bus
        await message_bus.publish(
            message_bus.chat_channel(family_id),
            {
                "id": str(msg.id),
                "sender_id": str(sender_id) if sender_id else None,
                "body": msg.body,
                "created_at": msg.created_at.isoformat(),
            },
        )

        # Notify everyone in the family except the sender.
        await FamilyChatService._fanout_notification(
            db, family_id, sender_id, body
        )
        return msg

    @staticmethod
    async def post_event_message(
        db: AsyncSession,
        family_id: UUID,
        body: str,
        *,
        sender_id: Optional[UUID] = None,
        image_url: Optional[str] = None,
    ) -> Optional[FamilyChatMessage]:
        """Post a system/activity card (a task or gig completion) into the family
        thread and wake the live SSE stream — the "Campfire" liveliness hook.

        Unlike ``post_message`` this deliberately does NOT fan out a per-recipient
        notification: completions are frequent, so they animate the shared chat
        without spamming everyone's notification bell. Reactions already work on
        any family_chat row by id, so the card is reaction-ready. ``image_url``
        carries the proof photo when the completion has one.

        Best-effort: any failure is swallowed (and the session rolled back) so a
        chat hiccup can never break the task-approval flow that calls it. MUST be
        invoked only after the caller has committed its own work — this method
        commits the new message row on its own.
        """
        try:
            body = (body or "").strip()
            if not body:
                return None
            msg = FamilyChatMessage(
                family_id=family_id,
                sender_id=sender_id,
                body=body[:2000],
                image_url=image_url,
            )
            db.add(msg)
            await db.commit()
            await db.refresh(msg)

            from app.core import message_bus
            await message_bus.publish(
                message_bus.chat_channel(family_id),
                {
                    "id": str(msg.id),
                    "sender_id": str(sender_id) if sender_id else None,
                    "body": msg.body,
                    "image_url": msg.image_url,
                    "created_at": msg.created_at.isoformat(),
                },
            )
            return msg
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "post_event_message failed (family %s)", family_id
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return None

    @staticmethod
    async def post_completion(
        db: AsyncSession,
        family_id: UUID,
        *,
        user_name: str,
        title: str,
        points: int,
        is_bonus: bool = False,
        image_url: Optional[str] = None,
        sender_id: Optional[UUID] = None,
    ) -> Optional[FamilyChatMessage]:
        """Auto-post a celebratory completion card into family chat (Spanish-first
        to match the app default). Used by the task-approval flow so approved
        chores/bonus tasks light up the shared thread with the proof photo
        attached. "Gig" wording is reserved for the cash gig board."""
        emoji = "\U0001F389" if is_bonus else "✅"  # 🎉 bonus / ✅ chore
        kind = "la tarea bonus" if is_bonus else "la tarea"
        pts_txt = f" (+{points} pts)" if points else ""
        body = f"{emoji} {user_name} completó {kind} «{title}»{pts_txt}"
        return await FamilyChatService.post_event_message(
            db,
            family_id,
            body,
            sender_id=sender_id,
            image_url=image_url,
        )

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
        family_id: UUID,
        after_ts: Optional[datetime] = None,
    ):
        """SSE generator. Emits `event: message` for each new message that
        appears after ``after_ts`` (default: now). Closes after
        ``STREAM_WINDOW_SECONDS`` so the client reconnects. Heartbeats
        every ~10s so proxies don't time out.

        Delivery is event-driven: ``post_message`` PUBLISHes to a family-scoped
        Redis channel and this generator wakes on that signal, then re-reads the
        DB (source of truth) so ordering + dedup stay identical to the old poll.
        A bounded fallback poll every ``FALLBACK_POLL_SECONDS`` still fires so a
        dropped publish can't lose a message, and if Redis is unreachable the
        stream degrades to pure polling.

        Uses a FRESH short-lived session per DB read (not a request-scoped
        Depends(get_db) session): the pooled connection must NOT be held across
        the wait window, or every open chat tab pins a connection
        ``idle in transaction`` and the pool (size 30) exhausts → app-wide 502s.
        """
        import time as _time

        from app.core import message_bus
        from app.core.database import AsyncSessionLocal

        cursor = after_ts or datetime.now(timezone.utc)

        async def _drain():
            """Yield SSE chunks for every message after ``cursor``, advancing it.

            Owns and closes its own short-lived session so no pooled connection
            is held across the wait window between drains.
            """
            nonlocal cursor
            async with AsyncSessionLocal() as s:
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
                rows = list((await s.execute(q)).scalars().all())
            # session closed here — connection back to the pool before we wait
            chunks = []
            for m in rows:
                payload = {
                    "id": str(m.id),
                    "sender_id": str(m.sender_id) if m.sender_id else None,
                    "body": m.body,
                    "image_url": m.image_url,
                    "created_at": m.created_at.isoformat(),
                }
                chunks.append(
                    "event: message\ndata: " + json.dumps(payload) + "\n\n"
                )
                cursor = m.created_at
            return chunks

        # Drain anything already newer than the cursor before we start waiting —
        # covers the reconnect gap between successive stream windows.
        for chunk in await _drain():
            yield chunk

        channel = message_bus.chat_channel(family_id)
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
