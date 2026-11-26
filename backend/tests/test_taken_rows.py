"""Rows a past take left behind. "Up for grabs" was removed 2026-11-25, but a
take that already happened stays in the table: the owner's row is TAKEN (a
miss, locked) and the taker's row (taken_from_id) carries the chore. These
invariants must keep holding for those rows."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.exceptions import ValidationException
from app.core.security import get_password_hash
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.bank_service import BankService
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


async def _take(db, owner_row, taker, day):
    """What a take left in the table: the owner's row TAKEN + the taker's own
    row pointing back at it (same template, day and week)."""
    row = TaskAssignment(
        family_id=owner_row.family_id, template_id=owner_row.template_id,
        assigned_to=taker.id, status=AssignmentStatus.PENDING,
        assigned_date=owner_row.assigned_date, week_of=owner_row.week_of,
        taken_from_id=owner_row.id)
    db.add(row)
    owner_row.status = AssignmentStatus.TAKEN
    owner_row.taken_by = taker.id
    owner_row.taken_at = _at(day, 21, 0)
    await db.commit()
    await db.refresh(row)
    return row


@pytest.fixture
async def ctx(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family)
    taker = await _user(db_session, test_family, "Taker")
    day = _today()
    tpl = await _tpl(db_session, test_family)
    a = await _assign(db_session, test_teen_user, tpl, day)
    return db_session, test_family, test_teen_user, taker, tpl, a, day




























async def test_owner_cannot_complete_after_take(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    await _take(db, a, taker, day)
    with pytest.raises(ValidationException):
        await TaskAssignmentService.complete_assignment(db, a.id, fam.id, owner.id)


async def test_mark_done_for_kid_rejects_taken(ctx, test_parent_user):
    db, fam, owner, taker, tpl, a, day = ctx
    await _take(db, a, taker, day)
    with pytest.raises(ValidationException):
        await TaskAssignmentService.mark_done_for_kid(
            db, a.id, fam.id, test_parent_user.id, note="she did it")


async def test_reshuffle_keeps_taken_rows(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    row = await _take(db, a, taker, day)
    row_id, a_id, week = row.id, a.id, a.week_of
    await TaskAssignmentService.shuffle_tasks(db, fam.id, week_of=week, today=day)
    db.expire_all()
    assert (await db.get(TaskAssignment, row_id)) is not None
    assert (await db.get(TaskAssignment, a_id)).status == AssignmentStatus.TAKEN


async def test_taken_counts_as_miss(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    await _take(db, a, taker, day)
    states = await ProgressService.day_states(db, fam.id, owner.id, day, MX)
    assert states[day] == DayState.missed
    done, assigned, lost = await BankService._chore_units(db, fam.id, owner.id, a.week_of)
    assert (done, assigned, lost) == (0, 1000, 1000)
    tasks = await BankService._chore_week_tasks(db, fam.id, owner.id, a.week_of)
    assert [(t["status"], t["earned_points"]) for t in tasks] == [("taken", 0)]


async def test_takers_row_never_expires(ctx):
    """The taker's row is not a covered chore: it can be finished after the
    day ended (the owner's own rows expire at midnight)."""
    db, fam, owner, taker, tpl, a, day = ctx
    row = await _take(db, a, taker, day)
    done = await TaskAssignmentService.complete_assignment(
        db, row.id, fam.id, taker.id, now=_at(day + timedelta(days=1), 8, 0))
    assert done.status == AssignmentStatus.COMPLETED


async def test_taker_completes_earns_points(ctx):
    db, fam, owner, taker, tpl, a, day = ctx
    row = await _take(db, a, taker, day)
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
    await _take(db, a, taker, day)
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
    await _take(db, await db.get(TaskAssignment, a_id), taker, day)
    for kw in ({"status": AssignmentStatus.PENDING}, {"status": AssignmentStatus.CANCELLED},
               {"assigned_to": taker_id}, {"assigned_date": day + timedelta(days=1)}):
        with pytest.raises(ValidationException, match="Madrugador"):
            await TaskAssignmentService.patch_assignment(db, a_id, fam_id, **kw)
        await db.rollback()
    a = await db.get(TaskAssignment, a_id, populate_existing=True)
    assert a.status == AssignmentStatus.TAKEN and a.assigned_to == owner_id
    assert a.assigned_date == day


async def test_taken_row_cannot_be_deleted(ctx):
    """I4: taken_from_id is ON DELETE SET NULL — deleting the owner's row would
    turn the taker's row into an ordinary covered chore."""
    db, fam, owner, taker, tpl, a, day = ctx
    a_id, fam_id = a.id, fam.id
    row = await _take(db, await db.get(TaskAssignment, a_id), taker, day)
    row_id = row.id
    with pytest.raises(ValidationException, match="Madrugador"):
        await TaskAssignmentService.delete_by_id(db, a_id, fam_id)
    await db.rollback()
    assert (await db.get(TaskAssignment, a_id)) is not None
    row = await db.get(TaskAssignment, row_id, populate_existing=True)
    assert row.taken_from_id == a_id




async def test_takers_row_cannot_be_moved_cancelled_or_deleted(ctx):
    """The taker's row holds the chore now: cancelling, moving or deleting it
    would leave the owner's row TAKEN with nobody doing the chore."""
    db, fam, owner, taker, tpl, a, day = ctx
    fam_id, owner_id = fam.id, owner.id
    row = await _take(db, a, taker, day)
    row_id = row.id
    for kw in ({"status": AssignmentStatus.CANCELLED}, {"assigned_to": owner_id},
               {"assigned_date": day + timedelta(days=1)}):
        with pytest.raises(ValidationException, match="Madrugador"):
            await TaskAssignmentService.patch_assignment(db, row_id, fam_id, **kw)
        await db.rollback()
    with pytest.raises(ValidationException, match="Madrugador"):
        await TaskAssignmentService.delete_by_id(db, row_id, fam_id)
    await db.rollback()
    row = await db.get(TaskAssignment, row_id, populate_existing=True)
    assert row is not None and row.status == AssignmentStatus.PENDING


async def test_takers_completed_row_can_still_be_reopened(ctx):
    """Sending the taker's own work back for a redo keeps the chore with them."""
    db, fam, owner, taker, tpl, a, day = ctx
    fam_id = fam.id
    row = await _take(db, a, taker, day)
    row_id = row.id
    row.status = AssignmentStatus.COMPLETED
    row.completed_at = _at(day, 12, 0)
    await db.commit()
    out = await TaskAssignmentService.patch_assignment(
        db, row_id, fam_id, status=AssignmentStatus.PENDING)
    assert out.status == AssignmentStatus.PENDING

