"""Chore rules v2: week_metrics, the single source of the weekly percentages."""
from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event

from app.core.security import get_password_hash
from app.models.family import Family
from app.models.task_assignment import ApprovalStatus as AP, AssignmentStatus as AS, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.early_bird_rules import CoveredRow, EarlyBirdConfig
from app.services.early_bird_service import EarlyBirdService

MX = ZoneInfo("America/Mexico_City")
MON = date(2026, 11, 2)
SUN = MON + timedelta(days=6)


def cfg(enabled=True, enabled_at=datetime(2026, 10, 1, tzinfo=MX)):
    return EarlyBirdConfig(
        enabled=enabled, enabled_at=enabled_at, deadline=time(11, 0), days=None,
        bonus_pct=20, week_pct=5, streak_cents=5000, tz=MX,
        cutoff=time(20, 30), grab_end=time(22, 30),
    )


def at(day, h, m=0):
    return datetime(day.year, day.month, day.day, h, m, tzinfo=MX)


def done(day, h, m=0, **kw):
    return CoveredRow(uuid4(), day, AS.COMPLETED, kw.pop("approval", AP.APPROVED),
                      kw.pop("grade", None), at(day, h, m), **kw)


def open_row(day, status=AS.PENDING):
    return CoveredRow(uuid4(), day, status, AP.NONE, None, None)


AFTER = at(SUN, 21)  # past Sunday's cutoff


def rows_for(n_early, n_late, n_open=0, n_taken=0):
    rows = [done(MON, 9) for _ in range(n_early)]
    rows += [done(MON, 15) for _ in range(n_late)]  # after deadline, before cutoff
    rows += [open_row(MON) for _ in range(n_open)]
    rows += [CoveredRow(uuid4(), MON, AS.TAKEN, AP.NONE, None, None) for _ in range(n_taken)]
    return rows


@pytest.mark.parametrize("early,late,open_,tier,pct", [
    (10, 0, 0, "bonus", 15),
    (9, 1, 0, "bonus", 10),
    (8, 2, 0, "bonus", 5),
    (7, 3, 0, "bonus", 0),
    (5, 4, 1, "per_task", 0),   # 9/10 completed
    (6, 0, 4, "per_task", 0),   # exactly 60 %
    (5, 0, 5, "no_pay", 0),
])
def test_ten_chore_boundaries(early, late, open_, tier, pct):
    r = EarlyBirdService._metrics_from_rows(cfg(), rows_for(early, late, open_), MON, AFTER)
    assert (r.tier, r.bonus_pct, r.total) == (tier, pct, 10)
    assert r.completed == early + late and r.early == early


def test_disabled_is_neutral():
    r = EarlyBirdService._metrics_from_rows(cfg(enabled=False), rows_for(10, 0), MON, AFTER)
    assert r.tier == "neutral" and r.total == 0


def test_week_of_enabling_is_neutral():
    c = cfg(enabled_at=at(MON, 12))  # switched on after Monday's deadline: never counts
    r = EarlyBirdService._metrics_from_rows(c, rows_for(10, 0), MON, AFTER)
    assert r.tier == "neutral"


def test_no_rows_is_neutral():
    assert EarlyBirdService._metrics_from_rows(cfg(), [], MON, AFTER).tier == "neutral"


def test_final_flips_at_sunday_cutoff_not_deadline():
    rows = rows_for(10, 0)
    c = cfg()
    assert not EarlyBirdService._metrics_from_rows(c, rows, MON, at(SUN, 11, 30)).final
    assert not EarlyBirdService._metrics_from_rows(c, rows, MON, at(SUN, 20, 29)).final
    assert EarlyBirdService._metrics_from_rows(c, rows, MON, at(SUN, 20, 30)).final


def test_taken_counts_in_total_not_completed():
    r = EarlyBirdService._metrics_from_rows(cfg(), rows_for(9, 0, n_taken=1), MON, AFTER)
    assert (r.total, r.completed, r.tier) == (10, 9, "per_task")


def test_pending_review_counts_only_after_grace():
    rows = [done(MON, 9, approval=AP.PENDING)]
    c = cfg()
    assert EarlyBirdService._metrics_from_rows(c, rows, MON, AFTER).completed == 0
    late = at(SUN + timedelta(days=8), 12)
    assert EarlyBirdService._metrics_from_rows(c, rows, MON, late).completed == 1


def test_unreviewed_work_keeps_the_week_provisional_until_grace():
    """R5: completed work still awaiting the parent's review keeps a week
    non-final past Sunday's cutoff — the ladder must not floor or bonus it on a
    count that will move. Once the grace passes the week is final and the row
    counts (existing grace rule)."""
    rows = rows_for(9, 0) + [done(MON, 9, approval=AP.PENDING)]
    c = cfg()
    r = EarlyBirdService._metrics_from_rows(c, rows, MON, AFTER)
    assert (r.final, r.completed, r.total) == (False, 9, 10)
    # Last day of the grace (today == Sunday + 7) is still inside it.
    r = EarlyBirdService._metrics_from_rows(c, rows, MON, at(SUN + timedelta(days=7), 23))
    assert r.final is False
    r = EarlyBirdService._metrics_from_rows(c, rows, MON, at(SUN + timedelta(days=8), 0, 1))
    assert (r.final, r.completed, r.tier, r.bonus_pct) == (True, 10, "bonus", 15)


def test_only_review_pending_blocks_final():
    """An open (status PENDING) or rejected row is not 'awaiting review': the
    week is final at the cutoff as before."""
    c = cfg()
    open_rows = rows_for(9, 0, n_open=1)
    assert EarlyBirdService._metrics_from_rows(c, open_rows, MON, AFTER).final is True
    rejected = rows_for(9, 0) + [done(MON, 9, approval=AP.REJECTED)]
    assert EarlyBirdService._metrics_from_rows(c, rejected, MON, AFTER).final is True
    assert EarlyBirdService._metrics_from_rows(c, rows_for(10, 0), MON, AFTER).final is True


# ------------------------------------------------------------------ DB-backed

async def _template(db, fam):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                     family_id=fam.id)
    db.add(t)
    await db.flush()
    return t


def _assignment(fam, t, kid, day, hh, status=AS.COMPLETED):
    return TaskAssignment(
        family_id=fam.id, template_id=t.id, assigned_to=kid.id, assigned_date=day,
        week_of=MON, status=status, approval_status=AP.APPROVED,
        completed_at=at(day, hh) if status == AS.COMPLETED else None)


async def _enable(db, fam):
    fam.timezone = "America/Mexico_City"
    fam.early_bird_enabled = True
    fam.early_bird_enabled_at = datetime(2026, 10, 1, tzinfo=MX)
    fam.early_bird_deadline = time(11, 0)
    fam.early_bird_days = None
    await db.commit()


def _user(fam, name, role):
    return User(email=f"{name}-{uuid4().hex[:6]}@test.com", password_hash=get_password_hash("x"),
                name=name, role=role, family_id=fam.id, email_verified=True, points=0)


@pytest.mark.asyncio
async def test_real_family_mirror_four_members(db_session, test_family):
    """2 parents + teen + child; only the teen's chores are covered. 10 chores
    done early plus one taken => 11 total? No: 10 early + 1 afternoon + 1 taken."""
    db = db_session
    await _enable(db, test_family)
    mom, dad = _user(test_family, "mom", UserRole.PARENT), _user(test_family, "dad", UserRole.PARENT)
    teen, kid = _user(test_family, "teen", UserRole.TEEN), _user(test_family, "kid", UserRole.CHILD)
    db.add_all([mom, dad, teen, kid])
    await db.flush()
    t = await _template(db, test_family)
    for i in range(7):
        d = MON + timedelta(days=i)
        db.add(_assignment(test_family, t, teen, d, 9))
        if i < 3:
            db.add(_assignment(test_family, t, teen, d, 9))
    db.add(_assignment(test_family, t, teen, SUN, 15))
    db.add(_assignment(test_family, t, teen, SUN, 0, status=AS.TAKEN))
    # other members' chores never count (covered = teens only)
    db.add(_assignment(test_family, t, kid, MON, 9))
    db.add(_assignment(test_family, t, mom, MON, 9))
    await db.commit()
    c = await EarlyBirdService.config(db, test_family.id)
    r = await EarlyBirdService.week_metrics(db, c, test_family.id, teen.id, MON, AFTER)
    # 7 + 3 = 10 early, 1 afternoon, 1 taken
    assert (r.total, r.completed, r.early, r.final) == (12, 11, 10, True)
    assert r.tier == "per_task"  # the taken chore is not completed


@pytest.mark.asyncio
async def test_other_family_rows_never_counted(db_session, test_family, test_teen_user):
    db = db_session
    await _enable(db, test_family)
    other = Family(name="Other")
    db.add(other)
    await db.flush()
    stranger = _user(other, "stranger", UserRole.TEEN)
    db.add(stranger)
    await db.flush()
    t_mine = await _template(db, test_family)
    t_other = await _template(db, other)
    db.add(_assignment(test_family, t_mine, test_teen_user, MON, 9))
    for _ in range(5):
        db.add(_assignment(other, t_other, stranger, MON, 9))
        # a foreign row pointed at MY teen must not leak either
        db.add(_assignment(other, t_other, test_teen_user, MON, 9))
    await db.commit()
    c = await EarlyBirdService.config(db, test_family.id)
    r = await EarlyBirdService.week_metrics(db, c, test_family.id, test_teen_user.id, MON, AFTER)
    assert r.total == 1 and r.tier == "bonus" and r.bonus_pct == 15


@pytest.mark.asyncio
async def test_single_query(db_session, test_family, test_teen_user):
    db = db_session
    await _enable(db, test_family)
    t = await _template(db, test_family)
    for i in range(10):
        db.add(_assignment(test_family, t, test_teen_user, MON + timedelta(days=i % 7), 9))
    await db.commit()
    c = await EarlyBirdService.config(db, test_family.id)
    seen = []
    bind = db.get_bind()
    sync_engine = getattr(bind, "sync_engine", bind)

    def count(conn, cursor, statement, *a):
        seen.append(statement)

    event.listen(sync_engine, "before_cursor_execute", count)
    try:
        r = await EarlyBirdService.week_metrics(db, c, test_family.id, test_teen_user.id, MON, AFTER)
    finally:
        event.remove(sync_engine, "before_cursor_execute", count)
    assert r.total == 10
    assert len(seen) == 1, seen
