"""Parent → kid nudge (UX-C2): POST /api/oversight/nudge/{kid_id}.

One push per kid per 3 h across BOTH parents, only while the kid still has
required work open (today or overdue), never across families.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.notification import Notification, NotificationType as NT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.oversight_service import NUDGE_COOLDOWN, NudgeRefused, OversightService

from conftest import family_local_today

PUSH = "app.services.push_service.PushService.send_to_user"


async def _login(client, email):
    res = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def parent_headers(client, test_parent_user):
    return await _login(client, "parent@test.com")


@pytest_asyncio.fixture
async def parent2_headers(client, test_parent_user_2):
    return await _login(client, "parent2@test.com")


@pytest_asyncio.fixture
async def child_headers(client, test_child_user):
    return await _login(client, "child@test.com")


async def _chore(db, family, kid, *, days_ago=0, bonus=False, status=AssignmentStatus.PENDING):
    today = await family_local_today(db, family.id)
    day = today - timedelta(days=days_ago)
    t = TaskTemplate(
        id=uuid4(), title="Dishes", points=10, interval_days=1,
        assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True,
        family_id=family.id,
    )
    db.add(t)
    await db.commit()
    a = TaskAssignment(
        family_id=family.id, template_id=t.id, assigned_to=kid.id, status=status,
        approval_status=ApprovalStatus.NONE, assigned_date=day,
        week_of=day - timedelta(days=day.weekday()),
    )
    db.add(a)
    await db.commit()
    return a


async def _nudges(db, kid_id):
    return list((await db.execute(
        select(Notification)
        .where(Notification.user_id == kid_id, Notification.type == NT.PARENT_NUDGE)
        .order_by(Notification.created_at)
    )).scalars().all())


async def _spanish(db, kid):
    kid.preferred_lang = "es"
    await db.commit()


class TestNudgeSends:
    async def test_nudge_sends_one_notification_with_push(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _spanish(db_session, test_child_user)
        await _chore(db_session, test_family, test_child_user)
        await _chore(db_session, test_family, test_child_user, days_ago=2, status=AssignmentStatus.OVERDUE)
        with patch(PUSH, new_callable=AsyncMock) as push:
            res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["sent"] is True and body["open"] == 2 and body["nudged_at"]
        rows = await _nudges(db_session, test_child_user.id)
        assert len(rows) == 1
        assert rows[0].title == "⏰ Te faltan 2 tareas"
        assert rows[0].body == "Test te lo recuerda · tócalo para verlas"
        assert rows[0].link == "/dashboard"
        push.assert_awaited_once()
        assert push.await_args.args[1] == test_child_user.id

    async def test_singular_copy(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _spanish(db_session, test_child_user)
        await _chore(db_session, test_family, test_child_user)
        with patch(PUSH, new_callable=AsyncMock):
            res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 200, res.text
        row = (await _nudges(db_session, test_child_user.id))[0]
        assert row.title == "⏰ Te falta 1 tarea"
        assert row.body == "Test te lo recuerda · tócala para verla"

    async def test_english_kid_gets_english_copy(
        self, client, db_session, parent_headers, test_family, test_teen_user,
    ):
        # preferred_lang defaults to "en"
        await _chore(db_session, test_family, test_teen_user)
        await _chore(db_session, test_family, test_teen_user)
        with patch(PUSH, new_callable=AsyncMock):
            res = await client.post(f"/api/oversight/nudge/{test_teen_user.id}", headers=parent_headers)
        assert res.status_code == 200, res.text
        row = (await _nudges(db_session, test_teen_user.id))[0]
        assert row.title == "⏰ 2 chores to go"
        assert row.body == "Test is reminding you · tap to see them"


class TestNudgeCooldown:
    async def test_second_nudge_within_3h_is_429(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user)
        with patch(PUSH, new_callable=AsyncMock):
            first = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
            second = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert first.status_code == 200
        assert second.status_code == 429
        body = second.json()
        assert body["detail"] == "nudge_cooldown"
        assert 0 < body["retry_after_seconds"] <= 3 * 3600
        assert second.headers["Retry-After"] == str(body["retry_after_seconds"])
        assert len(await _nudges(db_session, test_child_user.id)) == 1

    async def test_cooldown_is_shared_by_both_parents(
        self, client, db_session, parent_headers, parent2_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user)
        with patch(PUSH, new_callable=AsyncMock):
            first = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
            other = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent2_headers)
        assert first.status_code == 200
        assert other.status_code == 429

    async def test_after_cooldown_a_new_nudge_supersedes_the_old(
        self, db_session, test_family, test_parent_user, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user)
        with patch(PUSH, new_callable=AsyncMock):
            await OversightService.nudge(db_session, test_family.id, test_parent_user, test_child_user.id)
            almost = datetime.now(timezone.utc) + NUDGE_COOLDOWN - timedelta(minutes=1)
            with pytest.raises(NudgeRefused) as refused:
                await OversightService.nudge(
                    db_session, test_family.id, test_parent_user, test_child_user.id, now=almost,
                )
            assert refused.value.reason == "nudge_cooldown"
            assert 0 < refused.value.retry_after_seconds <= 120
            later = datetime.now(timezone.utc) + NUDGE_COOLDOWN + timedelta(minutes=1)
            result = await OversightService.nudge(
                db_session, test_family.id, test_parent_user, test_child_user.id, now=later,
            )
        assert result["sent"] is True
        rows = await _nudges(db_session, test_child_user.id)
        assert len(rows) == 2
        await db_session.refresh(rows[0])
        assert rows[0].is_read is True
        assert rows[1].is_read is False

    def test_cooldown_is_three_hours(self):
        assert NUDGE_COOLDOWN == timedelta(hours=3)


class TestNudgeRefusals:
    async def test_nothing_open_is_409(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user, status=AssignmentStatus.COMPLETED)
        res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 409
        assert res.json()["detail"] == "nothing_to_nudge"

    async def test_only_bonus_open_is_nothing_to_nudge(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user, bonus=True)
        await _chore(db_session, test_family, test_child_user, bonus=True, days_ago=1)
        res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 409

    async def test_kid_in_another_family_is_404(
        self, client, db_session, parent_headers, other_family,
    ):
        stranger = User(
            email="stranger.kid@test.com", password_hash=get_password_hash("password123"),
            name="Stranger", role=UserRole.TEEN, family_id=other_family.id, email_verified=True,
        )
        db_session.add(stranger)
        await db_session.commit()
        await _chore(db_session, other_family, stranger)
        res = await client.post(f"/api/oversight/nudge/{stranger.id}", headers=parent_headers)
        assert res.status_code == 404
        assert await _nudges(db_session, stranger.id) == []

    async def test_parent_target_is_404(
        self, client, parent_headers, test_parent_user_2,
    ):
        res = await client.post(f"/api/oversight/nudge/{test_parent_user_2.id}", headers=parent_headers)
        assert res.status_code == 404

    async def test_inactive_kid_is_404(
        self, client, db_session, parent_headers, test_family, test_child_user,
    ):
        await _chore(db_session, test_family, test_child_user)
        test_child_user.is_active = False
        await db_session.commit()
        res = await client.post(f"/api/oversight/nudge/{test_child_user.id}", headers=parent_headers)
        assert res.status_code == 404

    async def test_unknown_id_is_404(self, client, parent_headers):
        res = await client.post(f"/api/oversight/nudge/{uuid4()}", headers=parent_headers)
        assert res.status_code == 404

    async def test_kid_caller_is_403(self, client, child_headers, test_teen_user):
        res = await client.post(f"/api/oversight/nudge/{test_teen_user.id}", headers=child_headers)
        assert res.status_code == 403
