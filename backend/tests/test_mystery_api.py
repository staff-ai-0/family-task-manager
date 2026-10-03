"""UX-D4b mystery box endpoints."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.services.progress_service import ProgressService


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _perfect_day(db, kid):
    today, _tz = await ProgressService.family_today(db, kid.family_id)
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1, assignment_type=AssignmentType.AUTO,
                     is_bonus=False, is_active=True, family_id=kid.family_id)
    db.add(t)
    await db.commit()
    db.add(TaskAssignment(family_id=kid.family_id, template_id=t.id, assigned_to=kid.id, status=AssignmentStatus.COMPLETED,
                          approval_status=ApprovalStatus.NONE, assigned_date=today,
                          week_of=today - timedelta(days=today.weekday())))
    await db.commit()


class TestKid:
    async def test_requires_auth(self, client):
        assert (await client.get("/api/progress/mystery")).status_code in (401, 403)

    async def test_a_perfect_day_shows_a_box_and_it_opens_once(self, client, db_session, test_family, test_child_user):
        await _perfect_day(db_session, test_child_user)
        h = await _login(client, "child@test.com")
        r = await client.get("/api/progress/mystery", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["applies"] is True and body["enabled"] is True and len(body["unopened"]) == 1
        box_id = body["unopened"][0]["id"]
        o = await client.post(f"/api/progress/mystery/{box_id}/open", headers=h)
        assert o.status_code == 200 and o.json()["kind"] == "points" and 5 <= o.json()["points"] <= 20
        again = await client.post(f"/api/progress/mystery/{box_id}/open", headers=h)
        assert again.json() == o.json()
        after = (await client.get("/api/progress/mystery", headers=h)).json()
        assert after["unopened"] == [] and after["opened_today"]["id"] == box_id

    async def test_reading_the_boxes_scans_one_day_not_a_year(self, client, db_session, test_family, test_child_user, monkeypatch):
        from app.services import mystery_service
        from app.services.progress_service import ProgressService
        seen = {}
        real = ProgressService.day_states

        async def spy(db, family_id, user_id, today, tz, since=None):
            seen["since"] = since
            return await real(db, family_id, user_id, today, tz, since=since)

        monkeypatch.setattr(mystery_service.ProgressService, "day_states", staticmethod(spy))
        await client.get("/api/progress/mystery", headers=await _login(client, "child@test.com"))
        assert seen["since"] is not None and (seen["since"] - (datetime.now(timezone.utc).date())).days >= -2

    async def test_someone_elses_box_is_not_found(self, client, db_session, test_family, test_child_user, test_teen_user):
        await _perfect_day(db_session, test_child_user)
        box_id = (await client.get("/api/progress/mystery", headers=await _login(client, "child@test.com"))).json()["unopened"][0]["id"]
        r = await client.post(f"/api/progress/mystery/{box_id}/open", headers=await _login(client, "teen@test.com"))
        assert r.status_code == 404

    async def test_boxes_off_is_a_conflict(self, client, db_session, test_family, test_child_user):
        await _perfect_day(db_session, test_child_user)
        h = await _login(client, "child@test.com")
        box_id = (await client.get("/api/progress/mystery", headers=h)).json()["unopened"][0]["id"]
        test_family.mystery_box_points = 0
        await db_session.commit()
        assert (await client.post(f"/api/progress/mystery/{box_id}/open", headers=h)).status_code == 409
        assert (await client.get("/api/progress/mystery", headers=h)).json()["enabled"] is False

    async def test_a_parent_does_not_apply(self, client, test_parent_user, auth_headers):
        r = await client.get("/api/progress/mystery", headers=auth_headers)
        assert r.status_code == 200 and r.json() == {"applies": False, "enabled": False, "unopened": [], "opened_today": None}


class TestParent:
    async def test_jar_crud_and_deliveries(self, client, db_session, test_family, test_parent_user, test_child_user, auth_headers):
        assert (await client.get("/api/families/surprises", headers=auth_headers)).json() == []
        r = await client.post("/api/families/surprises", json={"title": " Pick dessert tonight ", "emoji": "🍨"}, headers=auth_headers)
        assert r.status_code == 201 and r.json()["title"] == "Pick dessert tonight" and r.json()["emoji"] == "🍨"
        sid = r.json()["id"]
        assert (await client.post("/api/families/surprises", json={"title": "   "}, headers=auth_headers)).status_code in (400, 422)
        assert (await client.post("/api/families/surprises", json={"title": "x" * 61}, headers=auth_headers)).status_code in (400, 422)
        await _perfect_day(db_session, test_child_user)
        kid = await _login(client, "child@test.com")
        box_id = (await client.get("/api/progress/mystery", headers=kid)).json()["unopened"][0]["id"]
        opened = (await client.post(f"/api/progress/mystery/{box_id}/open", headers=kid)).json()
        assert opened["kind"] == "surprise" and opened["surprise_title"] == "Pick dessert tonight"
        d = await client.get("/api/progress/mystery/deliveries", headers=auth_headers)
        assert d.status_code == 200 and [(x["kid_name"], x["surprise_title"]) for x in d.json()] == [("Test Child", "Pick dessert tonight")]
        assert (await client.post(f"/api/progress/mystery/{box_id}/delivered", headers=auth_headers)).status_code == 204
        assert (await client.get("/api/progress/mystery/deliveries", headers=auth_headers)).json() == []
        assert (await client.post(f"/api/progress/mystery/{box_id}/delivered", headers=auth_headers)).status_code == 404
        assert (await client.delete(f"/api/families/surprises/{sid}", headers=auth_headers)).status_code == 204
        assert (await client.delete(f"/api/families/surprises/{sid}", headers=auth_headers)).status_code == 404

    async def test_kids_cannot_touch_the_jar_or_deliveries(self, client, db_session, test_family, test_child_user):
        h = await _login(client, "child@test.com")
        assert (await client.get("/api/families/surprises", headers=h)).status_code in (401, 403)
        assert (await client.post("/api/families/surprises", json={"title": "x"}, headers=h)).status_code in (401, 403)
        assert (await client.get("/api/progress/mystery/deliveries", headers=h)).status_code in (401, 403, 404)
        assert (await client.post(f"/api/progress/mystery/{uuid4()}/delivered", headers=h)).status_code in (401, 403, 404)
