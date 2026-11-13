"""Early Bird: 10:00/10:30 reminders and the up-for-grabs pushes."""
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from app.core.security import get_password_hash
from app.models.family import Family
from app.models.notification import Notification
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.early_bird_rules import EarlyBirdConfig
from app.services.early_bird_service import EarlyBirdService

MX = ZoneInfo("America/Mexico_City")


def _today() -> date:
    return datetime.now(MX).date()


def _at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=MX).astimezone(timezone.utc)


async def _setup(db, family):
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


async def _tpl(db, family, *, exempt=False, allowed_roles=None, title="Dishes"):
    t = TaskTemplate(id=uuid4(), title=title, points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                     family_id=family.id, early_bird_exempt=exempt, allowed_roles=allowed_roles)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, tpl, day, status=AssignmentStatus.PENDING):
    a = TaskAssignment(family_id=tpl.family_id, template_id=tpl.id, assigned_to=kid.id,
                       status=status, assigned_date=day,
                       week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _stamp(db, when):
    """Notification.created_at is the real clock; the sweep's send record
    compares it to injected family-local instants, so pin it to ``when``."""
    await db.execute(update(Notification).values(created_at=when))
    await db.commit()


async def _rows(db, user, type_):
    return (await db.execute(select(Notification).where(
        Notification.user_id == getattr(user, 'id', user), Notification.type == type_)
        .order_by(Notification.created_at))).scalars().all()


@pytest.fixture
async def ctx(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family)
    tpl = await _tpl(db_session, test_family)
    a = await _assign(db_session, test_teen_user, tpl, _today())
    return db_session, test_family, test_teen_user, tpl, a, _today()


async def test_r1_sent_at_1000_local(ctx):
    db, fam, teen, tpl, a, day = ctx
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 10, 0))
    assert (res["reminders"], res["grabs"], res["paid"]) == (1, 0, 0)  # settled: neutral past weeks
    rows = await _rows(db, teen, "deadline_soon")
    assert len(rows) == 1
    assert rows[0].expires_at.astimezone(MX) == datetime.combine(day, time(11, 0), tzinfo=MX)
    assert "1 hora" in rows[0].title or "1 hour" in rows[0].title


async def test_nothing_at_1000_utc_when_local_0400(ctx):
    db, fam, teen, *_rest, day = ctx
    res = await EarlyBirdService.run_sweep(
        db, now=datetime.combine(day, time(10, 0), tzinfo=timezone.utc))
    assert res["reminders"] == 0 and await _rows(db, teen, "deadline_soon") == []


async def test_r1_not_resent_same_window(ctx):
    db, fam, teen, tpl, a, day = ctx
    await EarlyBirdService.run_sweep(db, now=_at(day, 10, 0))
    await _stamp(db, _at(day, 10, 0))
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 10, 5))
    assert res["reminders"] == 0
    assert len(await _rows(db, teen, "deadline_soon")) == 1


async def test_r2_sent_at_1030(ctx):
    db, fam, teen, tpl, a, day = ctx
    await EarlyBirdService.run_sweep(db, now=_at(day, 10, 0))
    await _stamp(db, _at(day, 10, 0))
    r1_ids = [r.id for r in await _rows(db, teen, "deadline_soon")]
    await EarlyBirdService.run_sweep(db, now=_at(day, 10, 30))
    # Pin the R2 row (real-clock created_at) so ordering is clock-independent.
    await db.execute(update(Notification).where(Notification.id.notin_(r1_ids))
                     .values(created_at=_at(day, 10, 30)))
    await db.commit()
    rows = await _rows(db, teen, "deadline_soon")
    assert len(rows) == 2
    assert rows[0].is_read is True and rows[1].is_read is False


async def test_late_start_sends_r2_only(ctx):
    db, fam, teen, tpl, a, day = ctx
    await EarlyBirdService.run_sweep(db, now=_at(day, 10, 40))
    rows = await _rows(db, teen, "deadline_soon")
    assert len(rows) == 1 and ("30 minutos" in rows[0].title or "30 minutes" in rows[0].title)


async def test_no_reminder_when_done(ctx):
    db, fam, teen, tpl, a, day = ctx
    a.status = AssignmentStatus.COMPLETED
    await db.commit()
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 10, 0))
    assert res["reminders"] == 0 and await _rows(db, teen, "deadline_soon") == []


async def test_child_and_exempt_ignored(ctx):
    db, fam, teen, tpl, a, day = ctx
    a.status = AssignmentStatus.COMPLETED  # teen has nothing open
    kid = await _user(db, fam, "Kiddo", UserRole.CHILD)
    ex = await _tpl(db, fam, exempt=True, title="Pet")
    await _assign(db, teen, ex, day)
    await _assign(db, kid, tpl, day)
    await db.commit()
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 10, 0))
    assert res["reminders"] == 0
    assert await _rows(db, kid, "deadline_soon") == []
    assert await _rows(db, teen, "deadline_soon") == []


async def test_grabs_pushes_at_cutoff(ctx):
    db, fam, teen, tpl, a, day = ctx
    sib = await _user(db, fam, "Sibling")
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 20, 30))
    assert res["grabs"] == 2
    owner_rows = await _rows(db, teen, "up_for_grabs")
    sib_rows = await _rows(db, sib, "up_for_grabs")
    assert len(owner_rows) == 1 and ("Se acabó" in owner_rows[0].title or "Time's up" in owner_rows[0].title)
    assert len(sib_rows) == 1
    assert "libre" in sib_rows[0].title or "up for grabs" in sib_rows[0].title
    assert sib_rows[0].expires_at.astimezone(MX) == datetime.combine(day + timedelta(days=1), time.min, tzinfo=MX)
    await _stamp(db, _at(day, 20, 30))
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 20, 35)))["grabs"] == 0
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 21, 5)))["grabs"] == 0
    assert len(await _rows(db, sib, "up_for_grabs")) == 1


async def test_grabs_respects_allowed_roles(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family)
    day = _today()
    tpl = await _tpl(db_session, test_family, allowed_roles=["teen"])
    await _assign(db_session, test_teen_user, tpl, day)
    kid = await _user(db_session, test_family, "Kiddo", UserRole.CHILD)
    await EarlyBirdService.run_sweep(db_session, now=_at(day, 20, 30))
    assert await _rows(db_session, kid, "up_for_grabs") == []
    assert len(await _rows(db_session, test_teen_user, "up_for_grabs")) == 1


async def test_disabled_or_inactive_day_noop(ctx):
    db, fam, teen, tpl, a, day = ctx
    fam.early_bird_days = [(day.weekday() + 1) % 7]
    await db.commit()
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 10, 0)))["reminders"] == 0
    fam.early_bird_days = None
    fam.early_bird_enabled = False
    await db.commit()
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 10, 0)))["reminders"] == 0
    assert await _rows(db, teen, "deadline_soon") == []


async def test_one_family_failure_isolated(ctx):
    db, fam, teen, tpl, a, day = ctx
    fam2 = Family(name="Second Family")
    db.add(fam2)
    await db.commit()
    await _setup(db, fam2)
    teen2 = await _user(db, fam2, "Teentwo")
    tpl2 = await _tpl(db, fam2)
    await _assign(db, teen2, tpl2, day)

    teen_id, teen2_id = teen.id, teen2.id
    real = EarlyBirdService.config
    bad = {"id": None}

    async def flaky(db_, family_id):
        if bad["id"] is None:
            bad["id"] = family_id
        if family_id == bad["id"]:
            raise RuntimeError("boom")
        return await real(db_, family_id)

    with patch.object(EarlyBirdService, "config", staticmethod(flaky)):
        res = await EarlyBirdService.run_sweep(db, now=_at(day, 10, 0))
    assert res["reminders"] == 1
    total = len(await _rows(db, teen_id, "deadline_soon")) + len(await _rows(db, teen2_id, "deadline_soon"))
    assert total == 1


def test_cron_registered():
    from app.main import _register_cron_jobs
    sched = AsyncIOScheduler()
    _register_cron_jobs(sched)
    assert sched.get_job("early_bird_sweep") is not None
