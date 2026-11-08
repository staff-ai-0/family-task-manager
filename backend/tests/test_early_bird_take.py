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
