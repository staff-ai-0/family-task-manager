"""Early Bird: weekly +N % on the chore paycheck for an all-early week."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.services.bank_service import BankService
from app.services.payout_receipt_service import record_receipt

MX = ZoneInfo("America/Mexico_City")


def _local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=MX).astimezone(timezone.utc)


def _this_monday() -> date:
    today = datetime.now(MX).date()
    return today - timedelta(days=today.weekday())


async def _setup(db, family, kid, *, mode="points_rate", enabled_ago=60, week_pct=5, cap=0):
    family.timezone = "America/Mexico_City"
    family.early_bird_enabled = True
    family.early_bird_enabled_at = datetime.now(timezone.utc) - timedelta(days=enabled_ago)
    family.early_bird_deadline = time(11, 0)
    family.early_bird_days = None
    family.early_bird_week_pct = week_pct
    family.point_value_cents = 100
    await db.commit()
    acct = await BankService.ensure_account(db, kid)
    acct.allowance_mode = mode
    acct.allowance_cents = cap
    await db.commit()


async def _chore(db, family, kid, day, *, hh=9, done=True, approval=ApprovalStatus.APPROVED,
                 points=10):
    t = TaskTemplate(id=uuid4(), title="Chore", points=points, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                     family_id=family.id)
    db.add(t)
    await db.flush()
    a = TaskAssignment(
        family_id=family.id, template_id=t.id, assigned_to=kid.id, assigned_date=day,
        week_of=day - timedelta(days=day.weekday()),
        status=AssignmentStatus.COMPLETED if done else AssignmentStatus.PENDING,
        approval_status=approval if done else ApprovalStatus.NONE,
        completed_at=_local(day, hh) if done else None,
    )
    db.add(a)
    await db.commit()
    return a


async def _four_early(db, family, kid, monday):
    for i in range(4):
        await _chore(db, family, kid, monday + timedelta(days=i))


@pytest.fixture
async def ctx(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family, test_teen_user)
    return db_session, test_family, test_teen_user, _this_monday() - timedelta(days=7)


async def _allowance_total(db, kid):
    rows = (await db.execute(select(CashTransaction).where(
        CashTransaction.user_id == kid.id,
        CashTransaction.type == CashTransactionType.ALLOWANCE))).scalars().all()
    return sum(r.amount_cents for r in rows), rows


@pytest.mark.asyncio
async def test_projection_adds_week_bonus(ctx):
    db, fam, kid, last = ctx
    await _four_early(db, fam, kid, last)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 4200
    assert p["early_bird_bonus_cents"] == 200
    weeks = await BankService.list_outstanding_weeks(db, kid, fam.id)
    w = next(x for x in weeks if x["week_of"] == last)
    assert w["amount_cents"] == 4200 and w["early_bird_bonus_cents"] == 200


@pytest.mark.asyncio
async def test_release_pays_bonus(ctx):
    db, fam, kid, last = ctx
    await _four_early(db, fam, kid, last)
    r = await BankService.release_chore_paycheck(db, kid, fam.id, last, entitled=False)
    assert r["amount_cents"] == 4200
    total, rows = await _allowance_total(db, kid)
    assert total == 4200
    assert any("+5% madrugador" in (x.description or "") for x in rows)


@pytest.mark.asyncio
async def test_receipt_confirm_consistent(ctx):
    db, fam, kid, last = ctx
    await _four_early(db, fam, kid, last)
    await record_receipt(
        db, kid, fam.id, folio="F-EB-1", receipt_date=None, concept="",
        amount_cents=4200, allocations=[{"week_of": last, "amount_cents": 4200}],
        released_by=kid.id,
    )
    total, rows = await _allowance_total(db, kid)
    assert total == 4200 and len(rows) == 1  # adjustment 0: no extra row


@pytest.mark.asyncio
async def test_missed_day_no_bonus(ctx):
    db, fam, kid, last = ctx
    for i in range(3):
        await _chore(db, fam, kid, last + timedelta(days=i))
    await _chore(db, fam, kid, last + timedelta(days=3), hh=12)  # after r1
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 4000 and p["early_bird_bonus_cents"] == 0


@pytest.mark.asyncio
async def test_current_week_no_bonus(ctx):
    db, fam, kid, _ = ctx
    monday = _this_monday()
    await _chore(db, fam, kid, monday)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, monday)
    assert p["early_bird_bonus_cents"] == 0


@pytest.mark.asyncio
async def test_pending_review_no_bonus_until_grace(ctx):
    db, fam, kid, last = ctx
    await _chore(db, fam, kid, last)
    await _chore(db, fam, kid, last + timedelta(days=1), approval=ApprovalStatus.PENDING)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["early_bird_bonus_cents"] == 0  # review still pending
    # Two weeks back is past the grace window: pending counts as early.
    old = last - timedelta(days=7)
    await _chore(db, fam, kid, old)
    await _chore(db, fam, kid, old + timedelta(days=1), approval=ApprovalStatus.PENDING)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, old)
    assert p["early_bird_bonus_cents"] == 50  # 5% of the one approved chore (1000)


@pytest.mark.asyncio
async def test_flat_mode_untouched(ctx):
    db, fam, kid, last = ctx
    await _setup(db, fam, kid, mode="flat")
    await _four_early(db, fam, kid, last)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 0 and p["early_bird_bonus_cents"] == 0


@pytest.mark.asyncio
async def test_week_pct_zero_off(ctx):
    db, fam, kid, last = ctx
    await _setup(db, fam, kid, week_pct=0)
    await _four_early(db, fam, kid, last)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 4000 and p["early_bird_bonus_cents"] == 0


@pytest.mark.asyncio
async def test_ineligible_enable_week_no_bonus(ctx):
    db, fam, kid, last = ctx
    fam.early_bird_enabled_at = _local(last, 12)  # after Monday's r1
    await db.commit()
    for i in range(1, 5):
        await _chore(db, fam, kid, last + timedelta(days=i))
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 4000 and p["early_bird_bonus_cents"] == 0


@pytest.mark.asyncio
async def test_current_week_bonus_counts_from_sunday_r1(ctx):
    """I6: the week is over for early-bird purposes at Sunday's R1 (10:00)."""
    from app.services.early_bird_service import EarlyBirdService

    db, fam, kid, _ = ctx
    monday = _this_monday()
    await _four_early(db, fam, kid, monday)
    sunday = monday + timedelta(days=6)
    before = datetime.combine(sunday, time(9, 30), tzinfo=MX)
    after = datetime.combine(sunday, time(10, 30), tzinfo=MX)
    assert await EarlyBirdService.week_bonus_cents(db, fam.id, kid.id, monday, 4000, before) == 0
    assert await EarlyBirdService.week_bonus_cents(db, fam.id, kid.id, monday, 4000, after) == 200
