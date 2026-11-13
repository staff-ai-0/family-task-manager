"""Early Bird HTTP surface: /api/early-bird/{me,family,grabs/{id}/take}."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.core.security import get_password_hash
from app.models.family import Family
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.early_bird_service import EarlyBirdService

MX = ZoneInfo("America/Mexico_City")


def _today() -> date:
    return datetime.now(MX).date()


def _at(day, hh, mm):
    return datetime.combine(day, time(hh, mm), tzinfo=MX)


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _enable(db, family):
    family.timezone = "America/Mexico_City"
    family.early_bird_enabled = True
    family.early_bird_enabled_at = datetime.now(timezone.utc) - timedelta(days=30)
    family.early_bird_deadline = time(11, 0)
    family.early_bird_days = None
    await db.commit()


async def _user(db, family, name, role=UserRole.TEEN):
    u = User(email=f"{name.lower()}-{uuid4().hex[:6]}@example.com",
             password_hash=get_password_hash("password123"), name=name, role=role,
             family_id=family.id, email_verified=True, points=0)
    db.add(u)
    await db.commit()
    return u


async def _chore(db, family, kid, day, title="Dishes", title_es=None):
    t = TaskTemplate(id=uuid4(), title=title, title_es=title_es, points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                     family_id=family.id)
    db.add(t)
    await db.commit()
    a = TaskAssignment(family_id=family.id, template_id=t.id, assigned_to=kid.id,
                       status=AssignmentStatus.PENDING, assigned_date=day,
                       week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


@pytest.fixture
def after_deadline(monkeypatch):
    """Freeze the service clock at 21:00 family-local today (inside the
    20:30-22:30 grab window; was 11:05 before chore rules v2)."""
    fixed = _at(_today(), 21, 0)
    monkeypatch.setattr(EarlyBirdService, "_now", staticmethod(lambda now=None: now or fixed))
    return fixed


async def test_me_teen_shape(client, db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    await _chore(db_session, test_family, test_teen_user, _today())
    r = await client.get("/api/early-bird/me", headers=await _login(client, "teen@test.com"))
    assert r.status_code == 200
    b = r.json()
    assert set(b) == {"enabled", "applies", "deadline", "cutoff_at", "deadline_at", "today",
                      "week", "week_result", "run_weeks", "weeks_to_payout", "streak_weeks", "streak_cents",
                      "week_pct", "bonus_pct", "grabs", "take_block", "open_today"}
    assert b["enabled"] is True and b["applies"] is True and b["deadline"] == "11:00"
    assert len(b["week"]) == 7 and b["week"][0]["date"] <= b["week"][6]["date"]
    assert b["streak_weeks"] == 3 and b["run_weeks"] == 0
    assert b["today"] in ("open", "missed")
    assert b["cutoff_at"] and b["deadline_at"]
    assert isinstance(b["streak_cents"], int) and isinstance(b["week_pct"], int)


async def test_me_open_today_counts_open_chores(client, db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    await _chore(db_session, test_family, test_teen_user, _today(), title="A")
    done = await _chore(db_session, test_family, test_teen_user, _today(), title="B")
    done.status = AssignmentStatus.COMPLETED
    done.completed_at = datetime.now(timezone.utc)
    await db_session.commit()
    b = (await client.get("/api/early-bird/me", headers=await _login(client, "teen@test.com"))).json()
    assert b["open_today"] == 1


async def test_me_parent_403(client, test_parent_user):
    r = await client.get("/api/early-bird/me", headers=await _login(client, "parent@test.com"))
    assert r.status_code == 403


async def test_me_disabled_family(client, test_teen_user):
    r = await client.get("/api/early-bird/me", headers=await _login(client, "teen@test.com"))
    b = r.json()
    assert r.status_code == 200
    assert b["enabled"] is False and b["applies"] is False
    assert b["week"] == [] and b["grabs"] == [] and b["today"] is None and b["take_block"] is None


async def test_me_child_does_not_apply_but_sees_grabs(
        client, db_session, test_family, test_teen_user, test_child_user, after_deadline):
    await _enable(db_session, test_family)
    await _chore(db_session, test_family, test_teen_user, _today(), title_es="Platos")
    test_child_user.preferred_lang = "es"
    await db_session.commit()
    b = (await client.get("/api/early-bird/me", headers=await _login(client, "child@test.com"))).json()
    assert b["applies"] is False and b["week"] == [] and b["today"] is None
    assert [g["title"] for g in b["grabs"]] == ["Platos"]
    assert set(b["grabs"][0]) == {"assignment_id", "title", "points", "owner_name"}
    assert b["take_block"] is None


async def test_me_owner_does_not_see_own_chore(
        client, db_session, test_family, test_teen_user, after_deadline):
    await _enable(db_session, test_family)
    await _chore(db_session, test_family, test_teen_user, _today())
    b = (await client.get("/api/early-bird/me", headers=await _login(client, "teen@test.com"))).json()
    assert b["grabs"] == []


async def test_take_endpoint_happy(
        client, db_session, test_family, test_teen_user, test_child_user, after_deadline):
    await _enable(db_session, test_family)
    a = await _chore(db_session, test_family, test_teen_user, _today())
    r = await client.post(f"/api/early-bird/grabs/{a.id}/take",
                          headers=await _login(client, "child@test.com"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assigned_to"] == str(test_child_user.id) and body["status"] == "pending"
    assert body["id"] != str(a.id)


async def test_take_endpoint_409_race(
        client, db_session, test_family, test_teen_user, test_child_user, after_deadline):
    await _enable(db_session, test_family)
    a = await _chore(db_session, test_family, test_teen_user, _today())
    other = await _user(db_session, test_family, "Other")
    first = await client.post(f"/api/early-bird/grabs/{a.id}/take",
                              headers=await _login(client, "child@test.com"))
    assert first.status_code == 200
    h = await _login(client, other.email)
    second = await client.post(f"/api/early-bird/grabs/{a.id}/take", headers=h)
    assert second.status_code == 409 and second.json()["message"] == "already_taken"


async def test_take_own_chore_403(client, db_session, test_family, test_teen_user, after_deadline):
    await _enable(db_session, test_family)
    a = await _chore(db_session, test_family, test_teen_user, _today())
    r = await client.post(f"/api/early-bird/grabs/{a.id}/take",
                          headers=await _login(client, "teen@test.com"))
    assert r.status_code == 403 and r.json()["message"] == "own_chore"


async def test_take_before_cutoff_409(client, db_session, test_family, test_teen_user,
                                        test_child_user, monkeypatch):
    await _enable(db_session, test_family)
    a = await _chore(db_session, test_family, test_teen_user, _today())
    early = _at(_today(), 11, 5)
    monkeypatch.setattr(EarlyBirdService, "_now", staticmethod(lambda now=None: now or early))
    r = await client.post(f"/api/early-bird/grabs/{a.id}/take",
                          headers=await _login(client, "child@test.com"))
    assert r.status_code == 409 and r.json()["message"] == "grab_window_closed"


async def test_take_cross_family_404(client, db_session, test_family, test_child_user,
                                     after_deadline):
    await _enable(db_session, test_family)
    other = Family(name="Other")
    db_session.add(other)
    await db_session.commit()
    await _enable(db_session, other)
    kid = await _user(db_session, other, "Foreign")
    a = await _chore(db_session, other, kid, _today())
    r = await client.post(f"/api/early-bird/grabs/{a.id}/take",
                          headers=await _login(client, "child@test.com"))
    assert r.status_code == 404


async def test_take_parent_allowed(client, db_session, test_family, test_parent_user,
                                   test_teen_user, after_deadline):
    # was 403 (kids only); chore rules v2 lets any active member take
    await _enable(db_session, test_family)
    a = await _chore(db_session, test_family, test_teen_user, _today())
    r = await client.post(f"/api/early-bird/grabs/{a.id}/take",
                          headers=await _login(client, "parent@test.com"))
    assert r.status_code == 200, r.text
    assert r.json()["assigned_to"] == str(test_parent_user.id)


async def test_family_overview_parent_only(client, db_session, test_family, test_parent_user,
                                           test_teen_user, test_child_user):
    await _enable(db_session, test_family)
    await _chore(db_session, test_family, test_teen_user, _today())
    assert (await client.get("/api/early-bird/family",
                             headers=await _login(client, "teen@test.com"))).status_code == 403
    r = await client.get("/api/early-bird/family", headers=await _login(client, "parent@test.com"))
    assert r.status_code == 200
    rows = r.json()
    assert [x["user_id"] for x in rows] == [str(test_teen_user.id)]
    assert set(rows[0]) == {"user_id", "name", "today", "week", "week_result", "run_weeks",
                          "weeks_to_payout", "streak_weeks"}
    assert len(rows[0]["week"]) == 7


async def test_me_service_week_states(db_session, test_family, test_teen_user):
    """Direct service call with an injected clock: past days neutral, future 'future'."""
    await _enable(db_session, test_family)
    now = _at(_today(), 9, 0)
    out = await EarlyBirdService.me(db_session, test_teen_user, now=now)
    today = now.date()
    states = {w["date"]: w["state"] for w in out["week"]}
    for d, s in states.items():
        if d > today:
            assert s == "future"
        elif d < today:
            assert s == "neutral"
    assert states[today] == "neutral" and out["today"] == "neutral"


async def test_weeks_to_payout_cycles(db_session, test_family, test_teen_user):
    """I5: run 0 -> 3, run 3 (just paid) -> 3, run 4 -> 2; /me and /family agree."""
    from app.models.early_bird_week import EarlyBirdWeek

    await _enable(db_session, test_family)
    parent = await _user(db_session, test_family, "Mom", UserRole.PARENT)
    now = _at(_today(), 9, 0)
    last_monday = _today() - timedelta(days=_today().weekday() + 7)
    for run, expected in ((0, 3), (3, 3), (4, 2)):
        await db_session.execute(
            EarlyBirdWeek.__table__.delete().where(EarlyBirdWeek.user_id == test_teen_user.id))
        if run:
            db_session.add(EarlyBirdWeek(
                family_id=test_family.id, user_id=test_teen_user.id,
                week_of=last_monday, result="early", run_weeks=run))
        await db_session.commit()
        me = await EarlyBirdService.me(db_session, test_teen_user, now=now)
        assert me["run_weeks"] == run and me["weeks_to_payout"] == expected
        fam = await EarlyBirdService.family_overview(db_session, parent, now=now)
        assert fam[0]["weeks_to_payout"] == expected


async def test_family_overview_excludes_other_family_teens(
        client, db_session, test_family, test_parent_user, test_teen_user):
    """m9: tenancy."""
    await _enable(db_session, test_family)
    other = Family(name="Other fam", timezone="America/Mexico_City")
    db_session.add(other)
    await db_session.commit()
    stranger = await _user(db_session, other, "Stranger")
    r = await client.get("/api/early-bird/family", headers=await _login(client, "parent@test.com"))
    ids = [x["user_id"] for x in r.json()]
    assert str(stranger.id) not in ids and str(test_teen_user.id) in ids


async def test_me_grabs_exclude_other_family_chores(
        client, db_session, test_family, test_teen_user, test_child_user, after_deadline):
    """m9: tenancy on the up-for-grabs list."""
    await _enable(db_session, test_family)
    other = Family(name="Other fam", timezone="America/Mexico_City")
    db_session.add(other)
    await db_session.commit()
    await _enable(db_session, other)
    stranger = await _user(db_session, other, "Stranger")
    await _chore(db_session, other, stranger, _today(), title="Foreign")
    await _chore(db_session, test_family, test_teen_user, _today(), title="Mine")
    b = (await client.get("/api/early-bird/me", headers=await _login(client, "child@test.com"))).json()
    assert [g["title"] for g in b["grabs"]] == ["Mine"]
