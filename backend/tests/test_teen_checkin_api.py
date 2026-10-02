"""Jarvis teen check-in endpoints."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import func, select

from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.services.progress_service import ProgressService

URL = "/api/jarvis/checkin"


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _late_chore(db, family, teen, *, days=2, enabled=True):
    family.teen_checkin_enabled = enabled
    await db.commit()
    today, _tz = await ProgressService.family_today(db, family.id)
    template = TaskTemplate(id=uuid4(), title="Take out the trash", title_es="Saca la basura", points=15,
                            interval_days=1, assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                            family_id=family.id)
    db.add(template)
    await db.commit()
    day = today - timedelta(days=days)
    a = TaskAssignment(family_id=family.id, template_id=template.id, assigned_to=teen.id,
                       status=AssignmentStatus.OVERDUE, approval_status=ApprovalStatus.NONE,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _count(db):
    return (await db.execute(select(func.count()).select_from(TeenCheckin))).scalar()


class TestGet:
    async def test_requires_auth(self, client):
        assert (await client.get(URL)).status_code in (401, 403)

    async def test_a_teen_gets_the_offer(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        r = await client.get(URL, headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200
        assert r.json() == {
            "offer": {"assignment_id": str(a.id), "title": "Take out the trash", "title_es": "Saca la basura",
                      "trigger": "late", "days_late": 2},
            "can_chat": False,
        }

    async def test_no_offer_is_a_plain_null(self, client, db_session, test_family, test_teen_user):
        await _late_chore(db_session, test_family, test_teen_user, enabled=None)
        r = await client.get(URL, headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200 and r.json() == {"offer": None, "can_chat": False}

    async def test_parents_and_children_get_no_offer(self, client, db_session, test_family, test_teen_user, test_parent_user, test_child_user):
        await _late_chore(db_session, test_family, test_teen_user)
        for email in ("parent@test.com", "child@test.com"):
            r = await client.get(URL, headers=await _login(client, email))
            assert r.status_code == 200 and r.json()["offer"] is None

    async def test_can_chat_follows_the_plan(self, client, db_session, test_family, test_teen_user):
        await _late_chore(db_session, test_family, test_teen_user)
        with patch("app.services.teen_checkin_service.family_tier_allows", new=AsyncMock(return_value=True)):
            r = await client.get(URL, headers=await _login(client, "teen@test.com"))
        assert r.json()["can_chat"] is True


class TestPost:
    async def test_requires_auth(self, client):
        r = await client.post(URL, json={"assignment_id": str(uuid4()), "outcome": "dismissed"})
        assert r.status_code in (401, 403)

    async def test_an_answer_is_saved(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        r = await client.post(URL, json={"assignment_id": str(a.id), "outcome": "answered", "reason": "not_clear"},
                              headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200 and r.json() == {"saved": True, "can_chat": False}
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.outcome, row.reason, row.note, row.user_id) == ("answered", "not_clear", None, test_teen_user.id)

    async def test_a_note_is_saved_for_an_open_reason(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        r = await client.post(URL, json={"assignment_id": str(a.id), "outcome": "answered", "reason": "other",
                                         "note": "  it is always my turn "},
                              headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200
        assert (await db_session.execute(select(TeenCheckin.note))).scalar_one() == "it is always my turn"

    async def test_not_now_is_saved_and_the_offer_is_gone(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        headers = await _login(client, "teen@test.com")
        r = await client.post(URL, json={"assignment_id": str(a.id), "outcome": "dismissed"}, headers=headers)
        assert r.status_code == 200
        assert (await client.get(URL, headers=headers)).json()["offer"] is None

    async def test_bad_bodies_are_refused_and_store_nothing(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        headers = await _login(client, "teen@test.com")
        base = {"assignment_id": str(a.id)}
        for body in (
            {**base, "outcome": "answered"},                                               # no reason
            {**base, "outcome": "answered", "reason": "because"},                          # unknown reason
            {**base, "outcome": "answered", "reason": "too_hard", "note": "my brother never does his"},
            {**base, "outcome": "answered", "reason": "other", "note": "x" * 201},
            {**base, "outcome": "dismissed", "reason": "forgot"},
            {**base, "outcome": "dismissed", "note": "hello"},
            {**base, "outcome": "maybe"},
            {"outcome": "dismissed"},                                                      # no assignment
        ):
            r = await client.post(URL, json=body, headers=headers)
            assert r.status_code == 422, body
        assert await _count(db_session) == 0

    async def test_a_chore_that_was_not_offered_is_a_conflict(self, client, db_session, test_family, test_teen_user):
        await _late_chore(db_session, test_family, test_teen_user)
        r = await client.post(URL, json={"assignment_id": str(uuid4()), "outcome": "answered", "reason": "forgot"},
                              headers=await _login(client, "teen@test.com"))
        assert r.status_code == 409
        assert await _count(db_session) == 0

    async def test_a_parent_cannot_answer_for_the_teen(self, client, db_session, test_family, test_teen_user, test_parent_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        r = await client.post(URL, json={"assignment_id": str(a.id), "outcome": "answered", "reason": "forgot"},
                              headers=await _login(client, "parent@test.com"))
        assert r.status_code == 409
        assert await _count(db_session) == 0

    async def test_a_double_tap_is_harmless(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        headers = await _login(client, "teen@test.com")
        body = {"assignment_id": str(a.id), "outcome": "answered", "reason": "forgot"}
        assert (await client.post(URL, json=body, headers=headers)).status_code == 200
        assert (await client.post(URL, json=body, headers=headers)).status_code == 200
        assert await _count(db_session) == 1
