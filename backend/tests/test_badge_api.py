"""UX-D2 badge endpoints + parent hub count."""
from datetime import timedelta
from uuid import uuid4

from app.models.family_cup import FamilyCupSeason
from app.models.gig import GigClaim, GigClaimStatus, GigOffering
from app.services.oversight_service import OversightService
from app.services.progress_service import ProgressService


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _cup(db, kid, weeks_ago):
    today, _ = await ProgressService.family_today(db, kid.family_id)
    monday = today - timedelta(days=today.weekday())
    db.add(FamilyCupSeason(family_id=kid.family_id, week_start=monday - timedelta(weeks=weeks_ago),
                           winner_user_id=kid.id, winner_name=kid.name, winner_points=10))
    await db.commit()


class TestGetBadges:
    async def test_child_gets_the_whole_shelf(self, client, test_child_user):
        r = await client.get("/api/progress/badges", headers=await _login(client, "child@test.com"))
        assert r.status_code == 200
        body = r.json()
        assert body["applies"] is True and len(body["badges"]) == 8
        assert body["badges"][0] == {"badge": "chores", "count": 0, "tier": 0, "next_target": 10, "earned_at": None}
        assert body["unseen"] == [] and body["earned_total"] == 0

    async def test_teen_applies(self, client, test_teen_user):
        r = await client.get("/api/progress/badges", headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200 and r.json()["applies"] is True

    async def test_parent_does_not_apply(self, client, test_parent_user):
        r = await client.get("/api/progress/badges", headers=await _login(client, "parent@test.com"))
        assert r.status_code == 200
        assert r.json() == {"applies": False, "badges": [], "unseen": [], "earned_total": 0}

    async def test_requires_auth(self, client):
        assert (await client.get("/api/progress/badges")).status_code in (401, 403)


class TestAck:
    async def test_ack_clears_unseen(self, client, db_session, test_child_user):
        await _cup(db_session, test_child_user, 1)
        h = await _login(client, "child@test.com")
        unseen = (await client.get("/api/progress/badges", headers=h)).json()["unseen"]
        assert [(u["badge"], u["tier"]) for u in unseen] == [("cup", 1)]
        r = await client.post("/api/progress/badges/ack", json={"ids": [unseen[0]["id"]]}, headers=h)
        assert r.status_code == 204
        body = (await client.get("/api/progress/badges", headers=h)).json()
        assert body["unseen"] == [] and body["earned_total"] == 1

    async def test_ack_ignores_someone_elses_id(self, client, db_session, test_child_user, test_teen_user):
        await _cup(db_session, test_teen_user, 1)
        ht = await _login(client, "teen@test.com")
        theirs = (await client.get("/api/progress/badges", headers=ht)).json()["unseen"][0]["id"]
        hc = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/badges/ack", json={"ids": [theirs]}, headers=hc)).status_code == 204
        assert len((await client.get("/api/progress/badges", headers=ht)).json()["unseen"]) == 1

    async def test_ack_bounds_and_parent(self, client, test_child_user, test_parent_user):
        h = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/badges/ack", json={"ids": []}, headers=h)).status_code == 422
        too_many = [str(uuid4()) for _ in range(25)]
        assert (await client.post("/api/progress/badges/ack", json={"ids": too_many}, headers=h)).status_code == 422
        assert (await client.post("/api/progress/badges/ack", json={"ids": ["nope"]}, headers=h)).status_code == 422
        hp = await _login(client, "parent@test.com")
        r = await client.post("/api/progress/badges/ack", json={"ids": [str(uuid4())]}, headers=hp)
        assert r.status_code == 404


class TestKidSummary:
    async def test_badge_count_per_kid(self, client, db_session, test_family, test_child_user, test_teen_user):
        await _cup(db_session, test_child_user, 1)
        await client.get("/api/progress/badges", headers=await _login(client, "child@test.com"))
        summary = await OversightService.get_summary(db_session, test_family.id)
        by_id = {m.user_id: m for m in summary.members}
        assert by_id[test_child_user.id].badge_count == 1
        assert by_id[test_teen_user.id].badge_count == 0
        assert isinstance(by_id[test_child_user.id].badge_count, int)

    async def test_badge_count_hides_gig_badges_when_the_module_is_off(self, client, db_session, test_family,
                                                                      test_child_user):
        gig = GigOffering(family_id=test_family.id, title="Wash the car", points=50)
        db_session.add(gig)
        await db_session.commit()
        db_session.add(GigClaim(gig_id=gig.id, family_id=test_family.id, claimed_by=test_child_user.id,
                                status=GigClaimStatus.APPROVED))
        await db_session.commit()
        await client.get("/api/progress/badges", headers=await _login(client, "child@test.com"))
        test_family.enabled_modules = ["chat"]
        await db_session.commit()
        summary = await OversightService.get_summary(db_session, test_family.id)
        assert summary.members[0].badge_count == 0
