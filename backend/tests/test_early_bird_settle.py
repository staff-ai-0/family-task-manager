"""Early Bird: weekly settlement + the 3rd-consecutive-early-week cash bonus."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.early_bird_week import EarlyBirdWeek
from app.models.notification import Notification
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User
from app.services.early_bird_service import EarlyBirdService

MX = ZoneInfo("America/Mexico_City")


def _local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=MX).astimezone(timezone.utc)


def _this_monday() -> date:
    today = datetime.now(MX).date()
    return today - timedelta(days=today.weekday())


def _wk(n: int) -> date:
    """Monday n weeks before this week (n=1 is last week)."""
    return _this_monday() - timedelta(weeks=n)


async def _setup(db, family, *, streak_cents=50000, enabled_weeks_ago=6):
    family.timezone = "America/Mexico_City"
    family.early_bird_enabled = True
    family.early_bird_enabled_at = datetime.now(timezone.utc) - timedelta(weeks=enabled_weeks_ago)
    family.early_bird_deadline = time(11, 0)
    family.early_bird_days = None
    family.early_bird_streak_cents = streak_cents
    await db.commit()


async def _week(db, family, kid, monday, kind, *, approval=ApprovalStatus.APPROVED, done=True):
    """kind: early | missed | neutral | pending."""
    if kind == "neutral":
        return
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                     family_id=family.id)
    db.add(t)
    await db.flush()
    hh = 12 if kind == "missed" else 9
    ap = ApprovalStatus.PENDING if kind == "pending" else approval
    db.add(TaskAssignment(
        family_id=family.id, template_id=t.id, assigned_to=kid.id, assigned_date=monday,
        week_of=monday, status=AssignmentStatus.COMPLETED, approval_status=ap,
        completed_at=_local(monday, hh)))
    await db.commit()


async def _build(db, fam, kid, kinds):
    """kinds oldest-first, ending at last week."""
    n = len(kinds)
    for i, k in enumerate(kinds):
        await _week(db, fam, kid, _wk(n - i), k)


def _now():
    # a Wednesday-ish instant safely after last week's end
    return _local(_this_monday() + timedelta(days=2), 12)


async def _runs(db, kid, since=None):
    """Rows from ``since`` (default: last 3 weeks; older empty weeks settle as
    neutral run-0 rows and are not what these tests are about)."""
    since = since or _wk(3)
    rows = (await db.execute(select(EarlyBirdWeek).where(
        EarlyBirdWeek.user_id == kid.id, EarlyBirdWeek.week_of >= since)
        .order_by(EarlyBirdWeek.week_of))).scalars().all()
    return [r.run_weeks for r in rows], rows


async def _credits(db, kid):
    return (await db.execute(select(CashTransaction).where(
        CashTransaction.user_id == kid.id,
        CashTransaction.type == CashTransactionType.BONUS))).scalars().all()


async def _notifs(db, user_id, key_type="early_bird_payout"):
    return (await db.execute(select(Notification).where(
        Notification.type == key_type))).scalars().all()


@pytest.fixture
async def ctx(db_session, test_family, test_teen_user, test_parent_user):
    await _setup(db_session, test_family)
    return db_session, test_family, test_teen_user


@pytest.mark.asyncio
async def test_three_early_weeks_pay_500(ctx, test_parent_user):
    parent = test_parent_user
    db, fam, kid = ctx
    await _build(db, fam, kid, ["early", "early", "early"])
    out = await EarlyBirdService.run_sweep(db, _now())
    assert out["settled"] == 3 and out["paid"] == 1
    runs, rows = await _runs(db, kid)
    assert runs == [1, 2, 3]
    assert rows[2].bonus_cents == 50000 and rows[2].paid_at is not None
    cr = await _credits(db, kid)
    assert sum(c.amount_cents for c in cr) == 50000
    await db.refresh(kid)
    assert kid.cash_cents == 50000
    notes = await _notifs(db, kid.id)
    assert any(n.user_id == kid.id for n in notes)
    # I7: one row per parent (pushable), never a user_id=NULL family broadcast.
    assert not any(n.user_id is None for n in notes)
    parent_notes = [n for n in notes if n.link == "/parent/payouts"]
    assert len(parent_notes) == 1 and parent_notes[0].user_id == parent.id


@pytest.mark.asyncio
async def test_second_run_no_double_pay(ctx):
    db, fam, kid = ctx
    await _build(db, fam, kid, ["early", "early", "early"])
    await EarlyBirdService.run_sweep(db, _now())
    out = await EarlyBirdService.run_sweep(db, _now())
    assert out["settled"] == 0 and out["paid"] == 0
    assert len(await _credits(db, kid)) == 1
    await db.refresh(kid)
    assert kid.cash_cents == 50000


@pytest.mark.asyncio
async def test_missed_resets_run(ctx):
    db, fam, kid = ctx
    await _build(db, fam, kid, ["early", "missed", "early"])
    await EarlyBirdService.run_sweep(db, _now())
    runs, _ = await _runs(db, kid)
    assert runs == [1, 0, 1]
    assert await _credits(db, kid) == []


@pytest.mark.asyncio
async def test_neutral_keeps_run(ctx):
    db, fam, kid = ctx
    await _setup(db, fam, enabled_weeks_ago=7)
    await _week(db, fam, kid, _wk(4), "early")
    await _week(db, fam, kid, _wk(3), "neutral")
    await _week(db, fam, kid, _wk(2), "early")
    await _week(db, fam, kid, _wk(1), "early")
    # lookback is 3 weeks: settle oldest (wk4) in an earlier sweep first
    await EarlyBirdService.run_sweep(db, _local(_wk(3) + timedelta(days=8), 12))
    await EarlyBirdService.run_sweep(db, _now())
    runs, _ = await _runs(db, kid, _wk(4))
    assert runs == [1, 1, 2, 3]
    assert len(await _credits(db, kid)) == 1


@pytest.mark.asyncio
async def test_pending_blocks_then_grace(ctx):
    db, fam, kid = ctx
    await _week(db, fam, kid, _wk(1), "pending")
    await EarlyBirdService.run_sweep(db, _now())
    runs, _ = await _runs(db, kid, _wk(1))
    assert runs == []
    later = _local(_wk(1) + timedelta(days=6 + 8), 12)
    await EarlyBirdService.run_sweep(db, later)
    runs, rows = await _runs(db, kid, _wk(1))
    assert runs[0] == 1 and rows[0].result == "early"  # later weeks carry the run


@pytest.mark.asyncio
async def test_gap_week_breaks_run(ctx):
    db, fam, kid = ctx
    await _build(db, fam, kid, ["early", "early", "early"])
    # re-enable later: the two oldest weeks become ineligible
    fam.early_bird_enabled_at = _local(_wk(2), 12)
    await db.commit()
    await EarlyBirdService.run_sweep(db, _now())
    runs, rows = await _runs(db, kid, _wk(2))
    assert runs == [1]  # run restarts: wk3/wk2 ineligible, not counted
    assert await _credits(db, kid) == []


@pytest.mark.asyncio
async def test_streak_cents_zero_no_pay(ctx):
    db, fam, kid = ctx
    await _setup(db, fam, streak_cents=0)
    await _build(db, fam, kid, ["early", "early", "early"])
    out = await EarlyBirdService.run_sweep(db, _now())
    assert out["paid"] == 0
    runs, rows = await _runs(db, kid)
    assert runs == [1, 2, 3] and rows[2].paid_at is None
    assert await _credits(db, kid) == []


@pytest.mark.asyncio
async def test_week_six_pays_again(ctx):
    db, fam, kid = ctx
    await _setup(db, fam, enabled_weeks_ago=8)
    for i, w in enumerate((6, 5, 4)):
        await _week(db, fam, kid, _wk(w), "early")
    await EarlyBirdService.run_sweep(db, _local(_wk(4) + timedelta(days=8), 12))
    for w in (3, 2, 1):
        await _week(db, fam, kid, _wk(w), "early")
    await EarlyBirdService.run_sweep(db, _now())
    runs, rows = await _runs(db, kid, _wk(6))
    assert runs == [1, 2, 3, 4, 5, 6]
    assert len(await _credits(db, kid)) == 2
    await db.refresh(kid)
    assert kid.cash_cents == 100000


@pytest.mark.asyncio
async def test_guarded_update_blocks_second_credit(ctx):
    """m8: a row already stamped paid_at must not credit again."""
    db, fam, kid = ctx
    await _build(db, fam, kid, ["early", "early", "early"])
    await EarlyBirdService.run_sweep(db, _now())
    _, rows = await _runs(db, kid)
    row = rows[2]
    assert row.paid_at is not None
    args = (fam.id, kid.id, row.id, row.run_weeks, row.bonus_cents)
    paid = await EarlyBirdService._pay_streak(db, *args, _now())  # rolls back
    assert paid is False
    credits = (await db.execute(select(CashTransaction).where(
        CashTransaction.user_id == args[1],
        CashTransaction.type == CashTransactionType.BONUS))).scalars().all()
    assert len(credits) == 1
    assert (await db.get(User, args[1], populate_existing=True)).cash_cents == 50000


@pytest.mark.asyncio
async def test_prize_is_fixed_when_the_week_settles(ctx):
    """A run-3 week that settled while the prize was 0 earned nothing; raising
    the prize later must not pay it retroactively."""
    db, fam, kid = ctx
    await _setup(db, fam, streak_cents=0)
    await _build(db, fam, kid, ["early", "early", "early"])
    await EarlyBirdService.run_sweep(db, _now())
    await _setup(db, fam, streak_cents=50000)
    out = await EarlyBirdService.run_sweep(db, _now())
    assert out["paid"] == 0
    assert await _credits(db, kid) == []
    await db.refresh(kid)
    assert kid.cash_cents == 0
