"""Early Bird: up-for-grabs list and take-over."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    ConflictException, ForbiddenException, NotFoundException, ValidationException,
)
from app.core.security import get_password_hash
from app.models.family import Family
from app.models.notification import Notification
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.bank_service import BankService
from app.services.early_bird_service import EarlyBirdService
from app.services.progress_service import DayState, ProgressService
from app.services.task_assignment_service import TaskAssignmentService

MX = ZoneInfo("America/Mexico_City")


def _today() -> date:
    return datetime.now(MX).date()


def _at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=MX)


async def _setup(db, family):
    family.timezone = "America/Mexico_City"
    family.early_bird_enabled = True
    family.early_bird_enabled_at = datetime.now(timezone.utc) - timedelta(days=30)
    family.early_bird_deadline = time(11, 0)
    family.early_bird_days = None
    family.early_bird_bonus_pct = 20
    await db.commit()


async def _user(db, family, name, role=UserRole.TEEN):
    u = User(email=f"{name.lower()}-{uuid4().hex[:6]}@example.com",
             password_hash=get_password_hash("password123"), name=name, role=role,
             family_id=family.id, email_verified=True, points=0)
    db.add(u)
    await db.commit()
    return u


async def _tpl(db, family, *, exempt=False, points=10, allowed_roles=None, title="Dishes"):
    t = TaskTemplate(id=uuid4(), title=title, points=points, interval_days=1,
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


@pytest.fixture
async def ctx(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family)
    taker = await _user(db_session, test_family, "Taker")
    day = _today()
    tpl = await _tpl(db_session, test_family)
    a = await _assign(db_session, test_teen_user, tpl, day)
    return db_session, test_family, test_teen_user, taker, tpl, a, day


async def test_grabbable_after_deadline_only(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    assert await EarlyBirdService.grabbable(db, fam.id, now=_at(day, 10, 59)) == []
    rows = await EarlyBirdService.grabbable(db, fam.id, now=_at(day, 11, 5))
    assert [r.assignment_id for r in rows] == [a.id]
    assert rows[0].owner_id == owner.id and rows[0].points == 10


async def test_take_moves_chore(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    row = await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))
    await db.refresh(a)
    assert a.status == AssignmentStatus.TAKEN and a.taken_by == taker.id and a.taken_at
    assert row.status == AssignmentStatus.PENDING and row.assigned_to == taker.id
    assert row.taken_from_id == a.id and row.template_id == tpl.id
    assert row.assigned_date == a.assigned_date and row.week_of == a.week_of
    notes = (await db.execute(select(Notification).where(
        Notification.user_id == owner.id, Notification.type == "chore_taken"))).scalars().all()
    assert len(notes) == 1
    assert await EarlyBirdService.grabbable(db, fam.id, now=_at(day, 11, 6)) == []


async def test_second_take_409(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    other = await _user(db, fam, "Other")
    await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))
    with pytest.raises(ConflictException, match="already_taken"):
        await EarlyBirdService.take(db, fam.id, other, a.id, now=_at(day, 11, 6))


async def test_take_own_chore_403(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    with pytest.raises(ForbiddenException, match="own_chore"):
        await EarlyBirdService.take(db, fam.id, owner, a.id, now=_at(day, 11, 5))


async def test_taker_with_open_chores_403(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    await _assign(db, taker, await _tpl(db, fam, title="Own"), day)
    with pytest.raises(ForbiddenException, match="finish_yours_first"):
        await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))


async def test_allowed_roles_blocks_child(db_session, test_family, test_teen_user, test_child_user):
    await _setup(db_session, test_family)
    day = _today()
    tpl = await _tpl(db_session, test_family, allowed_roles=["teen"])
    a = await _assign(db_session, test_teen_user, tpl, day)
    with pytest.raises(ForbiddenException, match="role_not_allowed"):
        await EarlyBirdService.take(db_session, test_family.id, test_child_user, a.id,
                                    now=_at(day, 11, 5))


async def test_child_can_take(db_session, test_family, test_teen_user, test_child_user):
    await _setup(db_session, test_family)
    day = _today()
    a = await _assign(db_session, test_teen_user, await _tpl(db_session, test_family), day)
    row = await EarlyBirdService.take(db_session, test_family.id, test_child_user, a.id,
                                      now=_at(day, 11, 5))
    assert row.assigned_to == test_child_user.id


async def test_parent_cannot_take_403(ctx, test_parent_user):
    db, fam, owner, taker, tpl, a, day = ctx
    with pytest.raises(ForbiddenException, match="not_kid"):
        await EarlyBirdService.take(db, fam.id, test_parent_user, a.id, now=_at(day, 11, 5))


async def test_other_family_404(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    with pytest.raises(NotFoundException):
        await EarlyBirdService.take(db, uuid4(), taker, a.id, now=_at(day, 11, 5))


async def test_before_deadline_not_grabbable_422(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    with pytest.raises(ValidationException, match="not_grabbable"):
        await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 10, 59))


async def test_exempt_not_grabbable_422(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family)
    taker = await _user(db_session, test_family, "Taker")
    day = _today()
    a = await _assign(db_session, test_teen_user, await _tpl(db_session, test_family, exempt=True), day)
    with pytest.raises(ValidationException, match="not_grabbable"):
        await EarlyBirdService.take(db_session, test_family.id, taker, a.id, now=_at(day, 11, 5))


async def test_yesterday_not_grabbable_422(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family)
    taker = await _user(db_session, test_family, "Taker")
    day = _today()
    a = await _assign(db_session, test_teen_user, await _tpl(db_session, test_family),
                      day - timedelta(days=1), status=AssignmentStatus.OVERDUE)
    with pytest.raises(ValidationException, match="not_grabbable"):
        await EarlyBirdService.take(db_session, test_family.id, taker, a.id, now=_at(day, 11, 5))


async def test_completed_not_grabbable_422(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    a.status = AssignmentStatus.COMPLETED
    await db.commit()
    with pytest.raises(ValidationException, match="not_grabbable"):
        await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))


async def test_owner_cannot_complete_after_take(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))
    with pytest.raises(ValidationException):
        await TaskAssignmentService.complete_assignment(db, a.id, fam.id, owner.id)


async def test_mark_done_for_kid_rejects_taken(ctx, test_parent_user):
    db, fam, owner, taker, tpl, a, day = ctx
    await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))
    with pytest.raises(ValidationException):
        await TaskAssignmentService.mark_done_for_kid(
            db, a.id, fam.id, test_parent_user.id, note="she did it")


async def test_reshuffle_keeps_taken_rows(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    row = await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))
    row_id, a_id, week = row.id, a.id, a.week_of
    await TaskAssignmentService.shuffle_tasks(db, fam.id, week_of=week, today=day)
    db.expire_all()
    assert (await db.get(TaskAssignment, row_id)) is not None
    assert (await db.get(TaskAssignment, a_id)).status == AssignmentStatus.TAKEN


async def test_taken_counts_as_miss(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))
    states = await ProgressService.day_states(db, fam.id, owner.id, day, MX)
    assert states[day] == DayState.missed
    done, assigned, lost = await BankService._chore_units(db, fam.id, owner.id, a.week_of)
    assert (done, assigned, lost) == (0, 1000, 1000)
    tasks = await BankService._chore_week_tasks(db, fam.id, owner.id, a.week_of)
    assert [(t["status"], t["earned_points"]) for t in tasks] == [("taken", 0)]


async def test_taker_completes_earns_points(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    row = await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))
    await TaskAssignmentService.complete_assignment(db, row.id, fam.id, taker.id)
    await db.refresh(taker)
    assert taker.points == 10
    bonus = (await db.execute(select(PointTransaction).where(
        PointTransaction.user_id == taker.id, PointTransaction.type == TransactionType.BONUS))).scalars().all()
    assert bonus == []


# ---------------------------------------------------------- final-review fixes

async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_taken_task_status_serializes_on_payout_endpoints(
        client, ctx, test_parent_user):
    """C1: a TAKEN chore must not 500 the payout-summary / outstanding / history."""
    db, fam, owner, taker, tpl, a, day = ctx
    acct = await BankService.ensure_account(db, owner)
    acct.allowance_mode = "chore_proportional"
    acct.allowance_cents = 20000
    await db.commit()
    await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))
    # A taken chore in last week too, so the outstanding list contains it.
    last = day - timedelta(days=7)
    t2 = await _tpl(db, fam, title="Last week")
    owner_row = await _assign(db, owner, t2, last, status=AssignmentStatus.TAKEN)
    await _assign(db, taker, t2, last)

    h = await _login(client, "parent@test.com")
    r = await client.get("/api/bank/payout-summary", headers=h)
    assert r.status_code == 200, r.text
    kid = next(k for k in r.json()["kids"] if k["user_id"] == str(owner.id))
    statuses = [t["status"] for t in kid["tasks"]] + [
        t["status"] for w in kid["outstanding_weeks"] for t in w["tasks"]]
    assert "taken" in statuses

    r = await client.get(f"/api/bank/chore-paycheck/{owner.id}/outstanding", headers=h)
    assert r.status_code == 200, r.text
    flat = [t["status"] for w in r.json()["weeks"] for t in w.get("tasks", [])]
    assert "taken" in flat
    r = await client.get(f"/api/bank/chore-paycheck/{owner.id}/history", headers=h)
    assert r.status_code == 200, r.text
    assert owner_row.status == AssignmentStatus.TAKEN


async def test_taken_row_cannot_be_patched(ctx):
    """I4: reopening / moving a TAKEN row would pay the chore twice."""
    db, fam, owner, taker, tpl, a, day = ctx
    a_id, fam_id, owner_id, taker_id = a.id, fam.id, owner.id, taker.id
    await EarlyBirdService.take(db, fam_id, taker, a_id, now=_at(day, 11, 5))
    for kw in ({"status": AssignmentStatus.PENDING}, {"status": AssignmentStatus.CANCELLED},
               {"assigned_to": taker_id}, {"assigned_date": day + timedelta(days=1)}):
        with pytest.raises(ValidationException, match="taken_row_locked"):
            await TaskAssignmentService.patch_assignment(db, a_id, fam_id, **kw)
        await db.rollback()
    a = await db.get(TaskAssignment, a_id, populate_existing=True)
    assert a.status == AssignmentStatus.TAKEN and a.assigned_to == owner_id
    assert a.assigned_date == day


async def test_taken_row_cannot_be_deleted(ctx):
    """I4: taken_from_id is ON DELETE SET NULL — deleting the owner's row would
    turn the taker's row into an ordinary grabbable chore."""
    db, fam, owner, taker, tpl, a, day = ctx
    a_id, fam_id = a.id, fam.id
    row = await EarlyBirdService.take(db, fam_id, taker, a_id, now=_at(day, 11, 5))
    row_id = row.id
    with pytest.raises(ValidationException, match="taken_row_locked"):
        await TaskAssignmentService.delete_by_id(db, a_id, fam_id)
    await db.rollback()
    assert (await db.get(TaskAssignment, a_id)) is not None
    row = await db.get(TaskAssignment, row_id, populate_existing=True)
    assert row.taken_from_id == a_id


async def test_chore_taken_notification_uses_owner_language(ctx):
    """m4: the title is rendered in the owner's language."""
    db, fam, owner, taker, tpl, a, day = ctx
    tpl.title_es = "Lavar platos"
    owner.preferred_lang = "es"
    await db.commit()
    await EarlyBirdService.take(db, fam.id, taker, a.id, now=_at(day, 11, 5))
    n = (await db.execute(select(Notification).where(
        Notification.user_id == owner.id, Notification.type == "chore_taken"))).scalars().one()
    assert "Lavar platos" in (n.title + (n.body or ""))
