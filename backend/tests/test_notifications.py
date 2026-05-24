"""Notification service tests (W3.2)."""

import pytest
from datetime import datetime, timedelta, timezone

from app.models.notification import Notification, NotificationType
from app.services.notification_service import NotificationService


class TestNotificationService:
    async def test_create_and_list_user_specific(
        self, db_session, test_family, test_child_user
    ):
        await NotificationService.create(
            db_session,
            family_id=test_family.id,
            user_id=test_child_user.id,
            type=NotificationType.GIG_APPROVED,
            title="Approved",
            body="Nice job",
        )
        rows = await NotificationService.list_for_user(
            db_session, test_child_user.id, test_family.id
        )
        assert len(rows) == 1
        assert rows[0].title == "Approved"

    async def test_family_wide_visible_to_member(
        self, db_session, test_family, test_child_user
    ):
        await NotificationService.create(
            db_session,
            family_id=test_family.id,
            user_id=None,  # family-wide
            type=NotificationType.GIG_PENDING_REVIEW,
            title="Pending",
        )
        rows = await NotificationService.list_for_user(
            db_session, test_child_user.id, test_family.id
        )
        assert any(r.title == "Pending" for r in rows)

    async def test_unread_count(
        self, db_session, test_family, test_child_user
    ):
        for i in range(3):
            await NotificationService.create(
                db_session,
                family_id=test_family.id,
                user_id=test_child_user.id,
                type=NotificationType.GIG_APPROVED,
                title=f"n{i}",
            )
        n = await NotificationService.unread_count(
            db_session, test_child_user.id, test_family.id
        )
        assert n == 3

    async def test_mark_read(
        self, db_session, test_family, test_child_user
    ):
        n = await NotificationService.create(
            db_session,
            family_id=test_family.id,
            user_id=test_child_user.id,
            type=NotificationType.GIG_APPROVED,
            title="Read me",
        )
        updated = await NotificationService.mark_read(
            db_session, n.id, test_child_user.id, test_family.id
        )
        assert updated.is_read is True
        assert updated.read_at is not None
        assert (
            await NotificationService.unread_count(
                db_session, test_child_user.id, test_family.id
            )
            == 0
        )

    async def test_mark_all_read(
        self, db_session, test_family, test_child_user
    ):
        for i in range(4):
            await NotificationService.create(
                db_session,
                family_id=test_family.id,
                user_id=test_child_user.id,
                type=NotificationType.GIG_APPROVED,
                title=f"n{i}",
            )
        count = await NotificationService.mark_all_read(
            db_session, test_child_user.id, test_family.id
        )
        assert count == 4

    async def test_expired_not_returned(
        self, db_session, test_family, test_child_user
    ):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await NotificationService.create(
            db_session,
            family_id=test_family.id,
            user_id=test_child_user.id,
            type=NotificationType.GIG_APPROVED,
            title="Expired",
            expires_at=past,
        )
        rows = await NotificationService.list_for_user(
            db_session, test_child_user.id, test_family.id
        )
        assert not any(r.title == "Expired" for r in rows)
