"""UX-D3 weekly quest endpoints + parent hub fields."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.weekly_quest import WeeklyQuest
from app.services.oversight_service import OversightService
from app.services.progress_service import ProgressService
from app.services.quest_service import week_monday


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_quest(db, kid, *, target=1, done=1):
    """A quest for this week plus `done` completed chores dated today."""
    today, _tz = await ProgressService.family_today(db, kid.family_id)
    week = week_monday(today)
    template = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                            assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                            family_id=kid.family_id)
    quest = WeeklyQuest(family_id=kid.family_id, user_id=kid.id, week_start=week, quest="on_time",
                        target=target, bonus_points=20, created_at=datetime.now(timezone.utc))
    db.add_all([template, quest])
    await db.commit()
    for _ in range(done):
        db.add(TaskAssignment(family_id=kid.family_id, template_id=template.id, assigned_to=kid.id,
                              status=AssignmentStatus.COMPLETED, approval_status=ApprovalStatus.NONE,
                              assigned_date=today, week_of=today - timedelta(days=today.weekday())))
    await db.commit()
    await db.refresh(quest)
    return quest


class TestGetQuest:
    async def test_child_without_work_gets_no_quest(self, client, test_child_user):
        r = await client.get("/api/progress/quest", headers=await _login(client, "child@test.com"))
        assert r.status_code == 200
        assert r.json() == {"applies": True, "gig_term": "gig", "quest": None, "celebrate": None}

    async def test_child_gets_the_quest_shape(self, client, db_session, test_child_user):
        quest = await _seed_quest(db_session, test_child_user, target=3, done=1)
        body = (await client.get("/api/progress/quest", headers=await _login(client, "child@test.com"))).json()
        assert body["applies"] is True and body["celebrate"] is None
        assert set(body["quest"]) == {"id", "quest", "target", "progress", "bonus_points", "week_start",
                                      "days_left", "completed"}
        assert body["quest"]["id"] == str(quest.id)
        assert (body["quest"]["quest"], body["quest"]["target"], body["quest"]["progress"]) == ("on_time", 3, 1)
        assert body["quest"]["completed"] is False and 1 <= body["quest"]["days_left"] <= 7

    async def test_teen_applies(self, client, test_teen_user):
        r = await client.get("/api/progress/quest", headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200 and r.json()["applies"] is True

    async def test_parent_does_not_apply(self, client, test_parent_user):
        r = await client.get("/api/progress/quest", headers=await _login(client, "parent@test.com"))
        assert r.status_code == 200
        assert r.json() == {"applies": False, "gig_term": "gig", "quest": None, "celebrate": None}

    async def test_requires_auth(self, client):
        assert (await client.get("/api/progress/quest")).status_code in (401, 403)


class TestAck:
    async def test_reaching_the_goal_pays_and_ack_clears_the_moment(self, client, db_session, test_child_user):
        quest = await _seed_quest(db_session, test_child_user)
        h = await _login(client, "child@test.com")
        body = (await client.get("/api/progress/quest", headers=h)).json()
        assert body["quest"]["completed"] is True
        assert body["celebrate"] == {"id": str(quest.id), "quest": "on_time", "target": 1,
                                     "bonus_points": 20, "last_week": False}
        assert (await client.post("/api/progress/quest/ack", json={"id": str(quest.id)}, headers=h)).status_code == 204
        after = (await client.get("/api/progress/quest", headers=h)).json()
        assert after["celebrate"] is None and after["quest"]["completed"] is True

    async def test_ack_bounds_and_parent(self, client, test_child_user, test_parent_user):
        h = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/quest/ack", json={"id": "nope"}, headers=h)).status_code == 422
        assert (await client.post("/api/progress/quest/ack", json={}, headers=h)).status_code == 422
        assert (await client.post("/api/progress/quest/ack", json={"id": str(uuid4())}, headers=h)).status_code == 204
        hp = await _login(client, "parent@test.com")
        r = await client.post("/api/progress/quest/ack", json={"id": str(uuid4())}, headers=hp)
        assert r.status_code == 404


class TestKidSummary:
    async def test_quest_fields_per_kid(self, db_session, test_family, test_child_user, test_teen_user):
        await _seed_quest(db_session, test_child_user, target=3, done=1)
        summary = await OversightService.get_summary(db_session, test_family.id)
        by_id = {m.user_id: m for m in summary.members}
        child, teen = by_id[test_child_user.id], by_id[test_teen_user.id]
        assert (child.quest_progress, child.quest_target, child.quest_done) == (1, 3, False)
        assert (teen.quest_progress, teen.quest_target, teen.quest_done) == (None, None, False)
        assert isinstance(child.quest_progress, int)

    async def test_quest_fields_are_empty_when_quests_are_off(self, db_session, test_family, test_child_user):
        await _seed_quest(db_session, test_child_user, target=3, done=1)
        test_family.quest_bonus_points = 0
        await db_session.commit()
        summary = await OversightService.get_summary(db_session, test_family.id)
        kid = summary.members[0]
        assert (kid.quest_progress, kid.quest_target, kid.quest_done) == (None, None, False)
