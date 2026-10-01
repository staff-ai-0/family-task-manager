"""UX-D3 weekly_quests table constraints + the family bonus setting."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.weekly_quest import WeeklyQuest

MON = date(2026, 9, 28)


def _quest(kid, *, week=MON, target=3, bonus=20):
    return WeeklyQuest(family_id=kid.family_id, user_id=kid.id, week_start=week, quest="on_time",
                       target=target, bonus_points=bonus, created_at=datetime.now(timezone.utc))


async def test_one_quest_per_kid_per_week(db_session, test_child_user):
    db_session.add(_quest(test_child_user))
    await db_session.commit()
    db_session.add(_quest(test_child_user))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_a_new_week_gets_a_new_quest(db_session, test_child_user):
    db_session.add_all([_quest(test_child_user), _quest(test_child_user, week=date(2026, 10, 5))])
    await db_session.commit()


async def test_target_must_be_at_least_one(db_session, test_child_user):
    db_session.add(_quest(test_child_user, target=0))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_new_quests_start_unpaid_and_unseen(db_session, test_child_user):
    q = _quest(test_child_user)
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)
    assert q.rewarded_at is None and q.seen_at is None and q.id is not None


class TestFamilySetting:
    async def test_default_is_twenty(self, client, auth_headers, test_family):
        r = await client.get("/api/families/me", headers=auth_headers)
        assert r.status_code == 200 and r.json()["quest_bonus_points"] == 20

    async def test_parent_can_change_it(self, client, auth_headers, db_session, test_family):
        r = await client.patch("/api/families/me", json={"quest_bonus_points": 35}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["quest_bonus_points"] == 35
        await db_session.refresh(test_family)
        assert test_family.quest_bonus_points == 35

    async def test_zero_is_allowed_and_bounds_are_enforced(self, client, auth_headers, test_family):
        assert (await client.patch("/api/families/me", json={"quest_bonus_points": 0}, headers=auth_headers)).status_code == 200
        assert (await client.patch("/api/families/me", json={"quest_bonus_points": -1}, headers=auth_headers)).status_code == 422
        assert (await client.patch("/api/families/me", json={"quest_bonus_points": 501}, headers=auth_headers)).status_code == 422

    async def test_an_undecided_family_reads_null(self, client, auth_headers, db_session, test_family):
        test_family.quest_bonus_points = None          # existed before UX-D3: has not decided yet
        await db_session.commit()
        r = await client.get("/api/families/me", headers=auth_headers)
        assert r.status_code == 200 and r.json()["quest_bonus_points"] is None

    async def test_an_undecided_family_can_turn_quests_on(self, client, auth_headers, db_session, test_family):
        test_family.quest_bonus_points = None
        await db_session.commit()
        r = await client.patch("/api/families/me", json={"quest_bonus_points": 20}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["quest_bonus_points"] == 20

    async def test_an_undecided_family_can_turn_quests_off(self, client, auth_headers, db_session, test_family):
        test_family.quest_bonus_points = None
        await db_session.commit()
        r = await client.patch("/api/families/me", json={"quest_bonus_points": 0}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["quest_bonus_points"] == 0

    async def test_a_kid_cannot_change_it(self, client, test_child_user):
        login = await client.post("/api/auth/login", json={"email": "child@test.com", "password": "password123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        r = await client.patch("/api/families/me", json={"quest_bonus_points": 500}, headers=h)
        assert r.status_code == 403
