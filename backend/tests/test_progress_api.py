"""UX-D1 progress endpoints + parent hub fields."""
from app.models.point_transaction import PointTransaction, TransactionType as PT
from app.services.oversight_service import OversightService


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _xp(db, kid, points):
    db.add(PointTransaction(type=PT.TASK_COMPLETED, points=points, user_id=kid.id,
                            family_id=kid.family_id, balance_before=0, balance_after=points))
    await db.commit()


class TestMe:
    async def test_new_kid_gets_rank_one_streak_zero(self, client, test_child_user):
        r = await client.get("/api/progress/me", headers=await _login(client, "child@test.com"))
        assert r.status_code == 200
        body = r.json()
        assert body["applies"] is True and body["rank"] == 1 and body["streak_days"] == 0
        assert body["celebrate_rank"] is None and len(body["week"]) == 7

    async def test_teen_applies(self, client, test_teen_user):
        r = await client.get("/api/progress/me", headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200 and r.json()["applies"] is True

    async def test_parent_does_not_apply(self, client, test_parent_user):
        r = await client.get("/api/progress/me", headers=await _login(client, "parent@test.com"))
        assert r.status_code == 200 and r.json()["applies"] is False

    async def test_requires_auth(self, client):
        assert (await client.get("/api/progress/me")).status_code in (401, 403)


class TestAck:
    async def test_ack_moves_up_only_and_never_past_held_rank(self, client, db_session, test_child_user):
        await _xp(db_session, test_child_user, 650)  # rank 4
        h = await _login(client, "child@test.com")
        assert (await client.get("/api/progress/me", headers=h)).json()["celebrate_rank"] == 4
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 9}, headers=h)).status_code == 204
        await db_session.refresh(test_child_user)
        assert test_child_user.last_seen_rank == 4          # clamped to the held rank
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 2}, headers=h)).status_code == 204
        await db_session.refresh(test_child_user)
        assert test_child_user.last_seen_rank == 4          # never moves down
        assert (await client.get("/api/progress/me", headers=h)).json()["celebrate_rank"] is None

    async def test_ack_bounds_and_parent(self, client, test_child_user, test_parent_user):
        h = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 0}, headers=h)).status_code == 422
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 11}, headers=h)).status_code == 422
        hp = await _login(client, "parent@test.com")
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 1}, headers=hp)).status_code == 404


class TestKidSummary:
    async def test_kid_summary_streak_rank_per_kid(self, db_session, test_family, test_child_user, test_teen_user):
        await _xp(db_session, test_child_user, 1200)   # rank 5
        await _xp(db_session, test_teen_user, 150)     # rank 2
        summary = await OversightService.get_summary(db_session, test_family.id)
        by_id = {m.user_id: m for m in summary.members}
        assert by_id[test_child_user.id].rank == 5
        assert by_id[test_teen_user.id].rank == 2
        assert isinstance(by_id[test_child_user.id].streak_days, int)


async def _correction(db, kid, points):
    """A parent correction: a negative row of an earning type (what reopening a chore writes)."""
    db.add(PointTransaction(type=PT.TASK_COMPLETED, points=-points, user_id=kid.id,
                            family_id=kid.family_id, balance_before=0, balance_after=0))
    await db.commit()


class TestCelebratedRankNeverDrops:
    async def test_a_correction_below_a_celebrated_rank_keeps_the_rank(self, client, db_session, test_child_user):
        kid = test_child_user
        await _xp(db_session, kid, 650)                           # rank 4 (600..999)
        h = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 4}, headers=h)).status_code == 204
        await db_session.refresh(kid)
        await _correction(db_session, kid, 100)                   # XP 550 = rank 3 by XP
        body = (await client.get("/api/progress/me", headers=h)).json()
        assert body["xp"] == 550
        assert (body["rank"], body["rank_floor_xp"], body["next_rank_xp"]) == (4, 600, 1000)
        assert body["celebrate_rank"] is None
        await _xp(db_session, kid, 100)                           # earned back: no second celebration
        again = (await client.get("/api/progress/me", headers=h)).json()
        assert (again["rank"], again["xp"], again["celebrate_rank"]) == (4, 650, None)

    async def test_an_uncelebrated_rank_is_not_held(self, client, db_session, test_child_user):
        kid = test_child_user
        await _xp(db_session, kid, 650)                           # reached rank 4, never dismissed the celebration
        await _correction(db_session, kid, 100)
        body = (await client.get("/api/progress/me", headers=await _login(client, "child@test.com"))).json()
        assert (body["rank"], body["rank_floor_xp"], body["next_rank_xp"]) == (3, 300, 600)
        assert body["celebrate_rank"] == 3                        # the rank XP supports is the one to celebrate

    async def test_a_real_rank_up_above_the_held_rank_still_celebrates(self, client, db_session, test_child_user):
        kid = test_child_user
        kid.last_seen_rank = 4
        await db_session.commit()
        await _xp(db_session, kid, 550)                           # below the held rank
        h = await _login(client, "child@test.com")
        assert (await client.get("/api/progress/me", headers=h)).json()["celebrate_rank"] is None
        await _xp(db_session, kid, 500)                           # 1050 = rank 5
        body = (await client.get("/api/progress/me", headers=h)).json()
        assert (body["rank"], body["celebrate_rank"]) == (5, 5)

    async def test_the_top_rank_is_held_too(self, client, db_session, test_child_user):
        kid = test_child_user
        kid.last_seen_rank = 10
        await db_session.commit()
        body = (await client.get("/api/progress/me", headers=await _login(client, "child@test.com"))).json()
        assert (body["rank"], body["rank_floor_xp"], body["next_rank_xp"], body["xp"]) == (10, 8000, None, 0)
        assert body["celebrate_rank"] is None

    async def test_ack_cannot_raise_the_held_rank_above_what_xp_supports(self, client, db_session, test_child_user):
        kid = test_child_user
        await _xp(db_session, kid, 150)                           # rank 2
        h = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 9}, headers=h)).status_code == 204
        await db_session.refresh(kid)
        assert kid.last_seen_rank == 2
        assert (await client.get("/api/progress/me", headers=h)).json()["rank"] == 2

    async def test_parent_hub_shows_the_held_rank(self, db_session, test_family, test_child_user):
        kid = test_child_user
        kid.last_seen_rank = 4
        await db_session.commit()
        await _xp(db_session, kid, 550)
        summary = await OversightService.get_summary(db_session, test_family.id)
        assert summary.members[0].rank == 4

