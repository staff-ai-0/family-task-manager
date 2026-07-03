"""Chat read receipts (W8.5) + emoji reactions (W8.6)."""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.core.exceptions import ValidationException
from app.models.family_chat_reaction import FamilyChatReaction
from app.services.family_chat_service import FamilyChatService


class TestReadReceipts:
    async def test_unread_zero_when_no_messages(
        self, db_session, test_family, test_child_user
    ):
        n = await FamilyChatService.unread_count(
            db_session, test_child_user.id, test_family.id
        )
        assert n == 0

    async def test_unread_counts_other_senders_only(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "1"
        )
        await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "2"
        )
        await FamilyChatService.post_message(
            db_session, test_family.id, test_child_user.id, "self"
        )
        n_child = await FamilyChatService.unread_count(
            db_session, test_child_user.id, test_family.id
        )
        assert n_child == 2  # only parent's messages

    async def test_mark_read_zeroes(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "hi"
        )
        await FamilyChatService.mark_read(db_session, test_child_user.id)
        n = await FamilyChatService.unread_count(
            db_session, test_child_user.id, test_family.id
        )
        assert n == 0


class TestReactions:
    async def test_add_reaction(
        self, db_session, test_family, test_parent_user
    ):
        msg = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "hello"
        )
        await FamilyChatService.add_reaction(
            db_session, msg.id, test_parent_user.id, test_family.id, "👍"
        )
        rows = (
            await db_session.execute(select(FamilyChatReaction))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].emoji == "👍"

    async def test_add_reaction_idempotent(
        self, db_session, test_family, test_parent_user
    ):
        msg = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "hi"
        )
        for _ in range(3):
            await FamilyChatService.add_reaction(
                db_session, msg.id, test_parent_user.id, test_family.id, "🎉"
            )
        rows = (
            await db_session.execute(select(FamilyChatReaction))
        ).scalars().all()
        assert len(rows) == 1

    async def test_remove_reaction(
        self, db_session, test_family, test_parent_user
    ):
        msg = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "hi"
        )
        await FamilyChatService.add_reaction(
            db_session, msg.id, test_parent_user.id, test_family.id, "❤️"
        )
        await FamilyChatService.remove_reaction(
            db_session, msg.id, test_parent_user.id, test_family.id, "❤️"
        )
        rows = (
            await db_session.execute(select(FamilyChatReaction))
        ).scalars().all()
        assert rows == []

    async def test_invalid_emoji_rejected(
        self, db_session, test_family, test_parent_user
    ):
        msg = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "hi"
        )
        with pytest.raises(ValidationException):
            await FamilyChatService.add_reaction(
                db_session, msg.id, test_parent_user.id, test_family.id, ""
            )
        with pytest.raises(ValidationException):
            await FamilyChatService.add_reaction(
                db_session, msg.id, test_parent_user.id, test_family.id, "x" * 32
            )

    async def test_message_from_other_family_rejected(
        self, db_session, test_family, test_parent_user
    ):
        from uuid import uuid4
        with pytest.raises(ValidationException):
            await FamilyChatService.add_reaction(
                db_session, uuid4(), test_parent_user.id, test_family.id, "👍"
            )

    async def test_reactions_for_messages_grouping(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        msg = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "hi"
        )
        await FamilyChatService.add_reaction(
            db_session, msg.id, test_parent_user.id, test_family.id, "👍"
        )
        await FamilyChatService.add_reaction(
            db_session, msg.id, test_child_user.id, test_family.id, "👍"
        )
        await FamilyChatService.add_reaction(
            db_session, msg.id, test_child_user.id, test_family.id, "🎉"
        )
        groups = await FamilyChatService.reactions_for_messages(
            db_session, [msg.id]
        )
        by_emoji = {g["emoji"]: g for g in groups[msg.id]}
        assert by_emoji["👍"]["count"] == 2
        assert by_emoji["🎉"]["count"] == 1

    async def test_reaction_endpoint_returns_authoritative_count(
        self, client, db_session, test_family, test_parent_user, test_child_user
    ):
        """POST/DELETE reactions return {emoji, count, mine} so the client can
        reconcile its optimistic chip to server truth."""
        from app.core.security import create_access_token

        msg = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "react"
        )
        # child already reacted 👍 → server count 1
        await FamilyChatService.add_reaction(
            db_session, msg.id, test_child_user.id, test_family.id, "👍"
        )
        await db_session.commit()

        tok = create_access_token(data={
            "sub": str(test_parent_user.id),
            "family_id": str(test_parent_user.family_id),
            "role": test_parent_user.role.value,
        })
        headers = {"Authorization": f"Bearer {tok}"}

        # Parent adds 👍 → authoritative count is 2, mine=true.
        r = await client.post(f"/api/chat/{msg.id}/reactions", json={"emoji": "👍"}, headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["emoji"] == "👍" and body["count"] == 2 and body["mine"] is True

        # Parent removes 👍 → count back to 1 (child's), mine=false.
        r = await client.delete(f"/api/chat/{msg.id}/reactions?emoji=%F0%9F%91%8D", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1 and body["mine"] is False
