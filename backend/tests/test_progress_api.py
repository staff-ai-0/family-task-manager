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
