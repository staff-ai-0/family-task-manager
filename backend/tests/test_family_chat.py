"""Family chat service tests (W8.1)."""

import pytest

from app.core.exceptions import ValidationException
from app.models.notification import Notification, NotificationType
from app.services.family_chat_service import FamilyChatService
from sqlalchemy import select


class TestPost:
    async def test_post_and_list(
        self, db_session, test_family, test_parent_user
    ):
        msg = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "Hello family"
        )
        assert msg.body == "Hello family"
        rows = await FamilyChatService.list_messages(db_session, test_family.id)
        assert len(rows) == 1
        assert rows[0].body == "Hello family"

    async def test_blank_body_rejected(
        self, db_session, test_family, test_parent_user
    ):
        with pytest.raises(ValidationException):
            await FamilyChatService.post_message(
                db_session, test_family.id, test_parent_user.id, "   "
            )

    async def test_too_long_rejected(
        self, db_session, test_family, test_parent_user
    ):
        with pytest.raises(ValidationException):
            await FamilyChatService.post_message(
                db_session, test_family.id, test_parent_user.id, "x" * 2001
            )

    async def test_strips_whitespace(
        self, db_session, test_family, test_parent_user
    ):
        msg = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "  hi  "
        )
        assert msg.body == "hi"


class TestFanout:
    async def test_notifies_other_members_not_sender(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "ping"
        )
        rows = (
            await db_session.execute(
                select(Notification).where(Notification.family_id == test_family.id)
            )
        ).scalars().all()
        recipients = {r.user_id for r in rows}
        assert test_child_user.id in recipients
        assert test_parent_user.id not in recipients


class TestPagination:
    async def test_before_id_returns_older(
        self, db_session, test_family, test_parent_user
    ):
        a = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "first"
        )
        b = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "second"
        )
        c = await FamilyChatService.post_message(
            db_session, test_family.id, test_parent_user.id, "third"
        )
        older = await FamilyChatService.list_messages(
            db_session, test_family.id, limit=10, before_id=c.id
        )
        bodies = [m.body for m in older]
        assert bodies == ["first", "second"]
