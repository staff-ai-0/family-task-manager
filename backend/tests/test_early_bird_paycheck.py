"""Early Bird on the chore paycheck — chore-rules-v2 pay ladder: a final week
with 100 % of covered chores completed earns +5/+10/+15 % by early share
(>= 80/90/100 % before the 11:00 deadline); under 60 % pays nothing. The flat
``early_bird_week_pct`` is retired (column kept, never read). The ladder's own
boundary matrix lives in test_chore_ladder_paycheck.py."""
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
    """4/4 completed, all before 11:00 → 100 % early → +15 % of 4000."""
    db, fam, kid, last = ctx
    await _four_early(db, fam, kid, last)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 4600
    assert p["early_bird_bonus_cents"] == 600
    weeks = await BankService.list_outstanding_weeks(db, kid, fam.id)
    w = next(x for x in weeks if x["week_of"] == last)
    assert w["amount_cents"] == 4600 and w["early_bird_bonus_cents"] == 600


@pytest.mark.asyncio
async def test_release_pays_bonus(ctx):
    db, fam, kid, last = ctx
    await _four_early(db, fam, kid, last)
    r = await BankService.release_chore_paycheck(db, kid, fam.id, last, entitled=False)
    assert r["amount_cents"] == 4600
    total, rows = await _allowance_total(db, kid)
    assert total == 4600
    assert any("+15% madrugador" in (x.description or "") for x in rows)


@pytest.mark.asyncio
async def test_receipt_confirm_consistent(ctx):
    db, fam, kid, last = ctx
    await _four_early(db, fam, kid, last)
    await record_receipt(
        db, kid, fam.id, folio="F-EB-1", receipt_date=None, concept="",
        amount_cents=4600, allocations=[{"week_of": last, "amount_cents": 4600}],
        released_by=kid.id,
    )
    total, rows = await _allowance_total(db, kid)
    assert total == 4600 and len(rows) == 1  # receipt == projection: adjustment 0


@pytest.mark.asyncio
async def test_missed_day_no_bonus(ctx):
    db, fam, kid, last = ctx
    for i in range(3):
        await _chore(db, fam, kid, last + timedelta(days=i))
    # After the 11:00 deadline (before the cutoff): 4/4 completed but only
    # 75 % early (< 80 %) → full per-task pay, no bonus.
    await _chore(db, fam, kid, last + timedelta(days=3), hh=12)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 4000 and p["early_bird_bonus_cents"] == 0


@pytest.mark.asyncio
async def test_current_week_no_bonus(ctx):
    """An in-progress week pays no bonus. `now` is pinned mid-week: through the
    real clock this asserted the wrong thing on Sunday evenings."""
    db, fam, kid, _ = ctx
    monday = _this_monday()
    await _chore(db, fam, kid, monday)
    acct = await BankService.ensure_account(db, kid)
    p = await BankService._paycheck_projection(
        db, acct, fam.id, monday, now=datetime.combine(monday, time(12, 0), tzinfo=MX))
    assert p["early_bird_bonus_cents"] == 0 and p["amount_cents"] == 1000
    assert p["ladder_final"] is False


@pytest.mark.asyncio
async def test_pending_review_no_bonus_until_grace(ctx):
    db, fam, kid, last = ctx
    await _chore(db, fam, kid, last)
    await _chore(db, fam, kid, last + timedelta(days=1), approval=ApprovalStatus.PENDING)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    # Review still pending (R5): the week stays provisional — 1 of 2 so far
    # would be no_pay, but an unreviewed count can still move, so no floor and
    # no bonus: the approved chore's plain per-task 1000.
    assert p["early_bird_bonus_cents"] == 0 and p["projected_cents"] == 1000
    assert (p["ladder_final"], p["ladder_tier"]) == (False, "no_pay")
    # Two weeks back is past the grace window: pending counts as completed and
    # early → 100 % / 100 % → +15 % of the one approved chore's 1000 (the
    # still-pending chore earns no per-task pay).
    old = last - timedelta(days=7)
    await _chore(db, fam, kid, old)
    await _chore(db, fam, kid, old + timedelta(days=1), approval=ApprovalStatus.PENDING)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, old)
    assert p["early_bird_bonus_cents"] == 150 and p["projected_cents"] == 1150


@pytest.mark.asyncio
async def test_flat_mode_untouched(ctx):
    db, fam, kid, last = ctx
    await _setup(db, fam, kid, mode="flat")
    await _four_early(db, fam, kid, last)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 0 and p["early_bird_bonus_cents"] == 0


@pytest.mark.asyncio
async def test_week_pct_column_is_retired(ctx):
    """early_bird_week_pct = 0 used to switch the weekly bonus off; the column is
    retired and the ladder pays on its own terms (+15 % for an all-early week)."""
    db, fam, kid, last = ctx
    await _setup(db, fam, kid, week_pct=0)
    await _four_early(db, fam, kid, last)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 4600 and p["early_bird_bonus_cents"] == 600


@pytest.mark.asyncio
async def test_ineligible_enable_week_no_bonus(ctx):
    db, fam, kid, last = ctx
    fam.early_bird_enabled_at = _local(last, 12)  # after Monday's 11:00 deadline
    await db.commit()
    for i in range(1, 5):
        await _chore(db, fam, kid, last + timedelta(days=i))
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, last)
    assert p["projected_cents"] == 4000 and p["early_bird_bonus_cents"] == 0


@pytest.mark.asyncio
async def test_current_week_bonus_counts_from_sunday_cutoff(ctx):
    """The pay week is final at Sunday's cutoff (20:30), not its 11:00 deadline:
    until then a chore can still be completed, so no bonus (and no floor)."""
    db, fam, kid, _ = ctx
    monday = _this_monday()
    await _four_early(db, fam, kid, monday)
    sunday = monday + timedelta(days=6)
    acct = await BankService.ensure_account(db, kid)

    async def bonus_at(hh, mm):
        p = await BankService._paycheck_projection(
            db, acct, fam.id, monday, now=datetime.combine(sunday, time(hh, mm), tzinfo=MX))
        return p["early_bird_bonus_cents"]

    assert await bonus_at(11, 30) == 0
    assert await bonus_at(20, 29) == 0
    assert await bonus_at(20, 30) == 600


@pytest.mark.asyncio
async def test_outstanding_weeks_carry_the_week_pct(ctx):
    """The payouts page labels '+N % madrugador' from the week itself, not from
    a second family fetch with a hard-coded fallback — N is the LADDER's % (the
    retired week_pct column, 7 here, is never read)."""
    db, fam, kid, last = ctx
    await _setup(db, fam, kid, week_pct=7)
    await _four_early(db, fam, kid, last)
    weeks = await BankService.list_outstanding_weeks(db, kid, fam.id)
    w = next(x for x in weeks if x["week_of"] == last)
    assert w["early_bird_bonus_cents"] == 600 and w["early_bird_week_pct"] == 15


@pytest.mark.asyncio
async def test_outstanding_week_response_carries_ladder_keys(ctx):
    from app.schemas.bank import PayoutPaycheckWeek

    db, fam, kid, last = ctx
    await _setup(db, fam, kid)
    await _four_early(db, fam, kid, last)
    weeks = await BankService.list_outstanding_weeks(db, kid, fam.id)
    w = next(x for x in weeks if x["week_of"] == last)
    assert {"ladder_tier", "completed_pct", "early_pct", "ladder_final"} <= set(w)
    out = PayoutPaycheckWeek(**w).model_dump()
    assert out["ladder_tier"] == "bonus" and out["completed_pct"] == 100
    assert out["early_pct"] == 100 and out["ladder_final"] is True


@pytest.mark.asyncio
async def test_outstanding_scan_loads_early_bird_config_once(ctx):
    """8 lookback weeks must not reload the family's Early Bird config 8 times."""
    from sqlalchemy import event

    db, fam, kid, last = ctx
    await _four_early(db, fam, kid, last)
    await _four_early(db, fam, kid, last - timedelta(days=7))
    loads = []

    def count(conn, cursor, statement, *args):
        if "early_bird_deadline" in statement and "FROM families" in statement:
            loads.append(statement)

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        await BankService.list_outstanding_weeks(db, kid, fam.id)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(loads) == 1, len(loads)
