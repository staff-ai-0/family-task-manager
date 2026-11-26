"""Early Bird HTTP surface: /api/early-bird/{me,family}."""
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
def evening(monkeypatch):
    """Freeze the service clock at 21:00 family-local today (inside what used
    to be the 20:30-22:30 grab window)."""
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
                      "week_ladder", "bonus_pct", "open_today",
                      "rules_version", "teen_alarm_1", "teen_alarm_2"}
    assert b["enabled"] is True and b["applies"] is True and b["deadline"] == "11:00"
    assert len(b["week"]) == 7 and b["week"][0]["date"] <= b["week"][6]["date"]
    assert b["streak_weeks"] == 3 and b["run_weeks"] == 0
    assert b["today"] in ("open", "missed")
    assert b["cutoff_at"] and b["deadline_at"]
    assert isinstance(b["streak_cents"], int) and "week_pct" not in b


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
    assert b["week"] == [] and b["today"] is None
    assert not {"grabs", "take_block", "grab_end_at"} & set(b)


async def test_me_child_does_not_apply_and_is_offered_nothing(
        client, db_session, test_family, test_teen_user, test_child_user, evening):
    """21:00, a sibling's chore still open: it used to be offered to the child."""
    await _enable(db_session, test_family)
    await _chore(db_session, test_family, test_teen_user, _today(), title_es="Platos")
    b = (await client.get("/api/early-bird/me", headers=await _login(client, "child@test.com"))).json()
    assert b["applies"] is False and b["week"] == [] and b["today"] is None
    assert not {"grabs", "take_block", "grab_end_at"} & set(b)


async def test_grab_endpoints_are_gone(
        client, db_session, test_family, test_teen_user, test_child_user, test_parent_user, evening):
    await _enable(db_session, test_family)
    a = await _chore(db_session, test_family, test_teen_user, _today())
    for email in ("child@test.com", "parent@test.com"):
        h = await _login(client, email)
        assert (await client.get("/api/early-bird/grabs", headers=h)).status_code == 404
        r = await client.post(f"/api/early-bird/grabs/{a.id}/take", headers=h)
        assert r.status_code == 404
    await db_session.refresh(a)
    assert a.status == AssignmentStatus.PENDING and a.assigned_to == test_teen_user.id
















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
                          "weeks_to_payout", "streak_weeks", "week_ladder"}
    assert set(rows[0]["week_ladder"]) == {"completed_pct", "early_pct", "tier", "bonus_pct", "final"}
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




# ---------------------------------------------------------------- task 6b

async def test_me_times_ladder_and_config(client, db_session, test_family, test_teen_user):
    """deadline_at is the 11:00 early deadline; cutoff_at is the end of the
    day — the next family-local midnight (America/Mexico_City, UTC-6)."""
    await _enable(db_session, test_family)
    await _chore(db_session, test_family, test_teen_user, _today())
    b = (await client.get("/api/early-bird/me", headers=await _login(client, "teen@test.com"))).json()
    assert "week_pct" not in b
    day = _today()

    def same(iso, hh, mm):
        return datetime.fromisoformat(iso) == _at(day, hh, mm)

    assert same(b["deadline_at"], 11, 0)
    assert datetime.fromisoformat(b["cutoff_at"]) == _at(day + timedelta(days=1), 0, 0)
    assert b["teen_alarm_1"] == "15:00" and b["teen_alarm_2"] == "19:00"
    assert b["rules_version"] == test_family.rules_version and isinstance(b["rules_version"], int)
    w = b["week_ladder"]
    assert set(w) == {"completed_pct", "early_pct", "tier", "bonus_pct", "final"}
    assert w["completed_pct"] == 0 and w["early_pct"] == 0 and w["final"] is False
    for k in ("completed_pct", "early_pct", "bonus_pct"):
        assert type(w[k]) is int
    assert isinstance(w["tier"], str)


async def test_me_week_ladder_counts(db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    now = _at(_today(), 21, 0)
    a = await _chore(db_session, test_family, test_teen_user, _today(), title="A")
    await _chore(db_session, test_family, test_teen_user, _today(), title="B")
    a.status = AssignmentStatus.COMPLETED
    a.completed_at = _at(_today(), 9, 0)
    await db_session.commit()
    out = await EarlyBirdService.me(db_session, test_teen_user, now=now)
    w = out["week_ladder"]
    assert w["completed_pct"] == 50 and w["early_pct"] == 50
    mom = await _user(db_session, test_family, "Mom2", UserRole.PARENT)
    fam = await EarlyBirdService.family_overview(db_session, mom, now=now)
    assert fam[0]["week_ladder"] == w








def test_early_bird_proxy_is_a_catch_all():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "frontend/src/pages/api/early-bird"
    assert (root / "[...path].ts").exists()
