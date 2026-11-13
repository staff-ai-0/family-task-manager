"""Early Bird: early bonus points on completion / approval, covered rows."""
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.family import Family
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.early_bird_service import EarlyBirdService
from app.services.task_assignment_service import TaskAssignmentService

MX = ZoneInfo("America/Mexico_City")


def _past_wednesday() -> date:
    d = date.today() - timedelta(days=10)
    return d + timedelta(days=(2 - d.weekday()) % 7)


def _local(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=MX).astimezone(timezone.utc)


def _frozen(instant):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)
    return FakeDT


async def _setup(db, family, *, enabled=True, days=None):
    family.timezone = "America/Mexico_City"
    family.early_bird_enabled = enabled
    family.early_bird_enabled_at = datetime.now(timezone.utc) - timedelta(days=30)
    family.early_bird_deadline = time(11, 0)
    family.early_bird_days = days
    family.early_bird_bonus_pct = 20
    await db.commit()


async def _template(db, family, *, bonus=False, exempt=False, proof=False, points=10):
    t = TaskTemplate(id=uuid4(), title="Chore", points=points, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True,
                     family_id=family.id, early_bird_exempt=exempt, requires_proof=proof)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, template, day, **kw):
    a = TaskAssignment(family_id=template.family_id, template_id=template.id, assigned_to=kid.id,
                       status=kw.pop("status", AssignmentStatus.PENDING), assigned_date=day,
                       week_of=day - timedelta(days=day.weekday()), **kw)
    db.add(a)
    await db.commit()
    return a


async def _complete(db, a, kid, instant, **kw):
    with patch("app.services.task_assignment_service.datetime", _frozen(instant)):
        await TaskAssignmentService.complete_assignment(db, a.id, a.family_id, kid.id, **kw)
    await db.refresh(a)


async def _bonus_rows(db, kid):
    return (await db.execute(select(PointTransaction).where(
        PointTransaction.user_id == kid.id, PointTransaction.type == TransactionType.BONUS))).scalars().all()


@pytest.fixture
async def ctx(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family)
    return db_session, test_family, test_teen_user, _past_wednesday()


async def test_complete_before_cutoff_awards_bonus(ctx):
    db, fam, kid, day = ctx
    a = await _assign(db, kid, await _template(db, fam), day)
    await _complete(db, a, kid, _local(day, 9, 59))
    await db.refresh(kid)
    rows = await _bonus_rows(db, kid)
    assert a.early_bonus_points == 2
    assert [r.points for r in rows] == [2]
    assert rows[0].description == "Madrugador +2"
    assert kid.points == 12


async def test_complete_at_cutoff_no_bonus(ctx):
    db, fam, kid, day = ctx
    a = await _assign(db, kid, await _template(db, fam), day)
    await _complete(db, a, kid, _local(day, 11, 0))
    await db.refresh(kid)
    assert a.early_bonus_points is None
    assert await _bonus_rows(db, kid) == []
    assert kid.points == 10


async def test_child_owner_no_bonus(db_session, test_family, test_child_user):
    await _setup(db_session, test_family)
    day = _past_wednesday()
    a = await _assign(db_session, test_child_user, await _template(db_session, test_family), day)
    await _complete(db_session, a, test_child_user, _local(day, 9, 0))
    assert a.early_bonus_points is None
    assert await _bonus_rows(db_session, test_child_user) == []


async def test_exempt_template_no_bonus(ctx):
    db, fam, kid, day = ctx
    a = await _assign(db, kid, await _template(db, fam, exempt=True), day)
    await _complete(db, a, kid, _local(day, 9, 0))
    assert a.early_bonus_points is None


async def test_disabled_family_no_bonus(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family, enabled=False)
    day = _past_wednesday()
    a = await _assign(db_session, test_teen_user, await _template(db_session, test_family), day)
    await _complete(db_session, a, test_teen_user, _local(day, 9, 0))
    assert a.early_bonus_points is None


async def test_inactive_weekday_no_bonus(db_session, test_family, test_teen_user):
    day = _past_wednesday()
    await _setup(db_session, test_family, days=[(day.weekday() + 1) % 7])
    a = await _assign(db_session, test_teen_user, await _template(db_session, test_family), day)
    await _complete(db_session, a, test_teen_user, _local(day, 9, 0))
    assert a.early_bonus_points is None


async def _approve(db, a, **kw):
    parent = (await db.execute(select(User).where(User.family_id == a.family_id, User.role == UserRole.PARENT))).scalar_one()
    await TaskAssignmentService.approve_gig(db, a.id, a.family_id, parent.id, **kw)
    await db.refresh(a)


async def _proof_chore(ctx):
    db, fam, kid, day = ctx
    a = await _assign(db, kid, await _template(db, fam, proof=True), day)
    await _complete(db, a, kid, _local(day, 9, 30), proof_image_url="/uploads/gig-proofs/0123456789abcdef0123456789abcdef.jpg")
    assert a.approval_status == ApprovalStatus.PENDING
    assert a.early_bonus_points is None
    return a


async def test_proof_chore_bonus_on_full_approval(ctx, test_parent_user):
    a = await _proof_chore(ctx)
    await _approve(ctx[0], a, approve=True, grade="full")
    assert a.early_bonus_points == 2
    assert len(await _bonus_rows(ctx[0], ctx[2])) == 1


async def test_proof_chore_partial_no_bonus(ctx, test_parent_user):
    a = await _proof_chore(ctx)
    await _approve(ctx[0], a, approve=True, grade="partial", partial_credit_pct=50)
    assert a.early_bonus_points is None
    assert await _bonus_rows(ctx[0], ctx[2]) == []


async def test_proof_chore_rejected_no_bonus(ctx, test_parent_user):
    a = await _proof_chore(ctx)
    await _approve(ctx[0], a, approve=False)
    assert a.early_bonus_points is None
    assert await _bonus_rows(ctx[0], ctx[2]) == []


async def test_parent_marked_same_morning_never_earns_the_early_bonus(ctx, test_parent_user):
    """Marked done by a parent at 10:30 — before the 11:00 deadline — and
    approved in full: a retroactive record never earns the +20 % early bonus."""
    db, fam, kid, day = ctx
    a = await _assign(db, kid, await _template(db, fam), day)
    with patch("app.services.task_assignment_service.datetime", _frozen(_local(day, 10, 30))):
        await TaskAssignmentService.mark_done_for_kid(
            db, a.id, fam.id, test_parent_user.id, note="she did it")
    await db.refresh(a)
    assert a.marked_done_by_parent is True
    assert a.completed_at == _local(day, 10, 30)
    await _approve(db, a, approve=True, grade="full")
    assert a.approval_status == ApprovalStatus.APPROVED
    assert a.early_bonus_points is None
    assert await _bonus_rows(db, kid) == []


async def test_bonus_idempotent(ctx):
    db, fam, kid, day = ctx
    t = await _template(db, fam)
    a = await _assign(db, kid, t, day, status=AssignmentStatus.COMPLETED,
                      completed_at=_local(day, 9, 0))
    assert await EarlyBirdService.maybe_award_early_bonus(db, a, t) == 2
    assert await EarlyBirdService.maybe_award_early_bonus(db, a, t) == 0
    await db.commit()
    assert len(await _bonus_rows(db, kid)) == 1


async def test_covered_rows_filters(ctx, test_child_user):
    db, fam, kid, day = ctx
    tmpl = await _template(db, fam)
    keep = await _assign(db, kid, tmpl, day)
    await _assign(db, kid, await _template(db, fam, bonus=True), day)
    await _assign(db, kid, await _template(db, fam, exempt=True), day)
    await _assign(db, test_child_user, tmpl, day)
    await _assign(db, kid, tmpl, day, taken_from_id=keep.id)
    await _assign(db, kid, tmpl, day, status=AssignmentStatus.CANCELLED)
    other = Family(name="Other")
    db.add(other)
    await db.commit()
    ot = await _template(db, other)
    await _assign(db, kid, ot, day)  # same kid id, other family's template/row
    cfg = await EarlyBirdService.config(db, fam.id)
    rows = await EarlyBirdService.covered_rows(db, cfg, fam.id, kid.id, day, day)
    assert [r.assignment_id for r in rows] == [keep.id]


async def _undo_setup(ctx):
    db, fam, kid, day = ctx
    a = await _assign(db, kid, await _template(db, fam), day)
    await _complete(db, a, kid, _local(day, 9, 0))
    await db.refresh(kid)
    assert a.early_bonus_points == 2 and kid.points == 12
    return a


async def _check_clawed_back(db, a, kid):
    await db.refresh(kid)
    await db.refresh(a)
    assert kid.points == 0
    assert a.early_bonus_points is None
    assert sorted(r.points for r in await _bonus_rows(db, kid)) == [-2, 2]


async def test_revive_claws_back_early_bonus(ctx):
    db, fam, kid, _ = ctx
    a = await _undo_setup(ctx)
    await TaskAssignmentService.patch_assignment(db, a.id, fam.id, status=AssignmentStatus.PENDING)
    await _check_clawed_back(db, a, kid)


async def test_cancel_claws_back_early_bonus(ctx):
    db, fam, kid, _ = ctx
    a = await _undo_setup(ctx)
    await TaskAssignmentService.patch_assignment(db, a.id, fam.id, status=AssignmentStatus.CANCELLED)
    await _check_clawed_back(db, a, kid)
