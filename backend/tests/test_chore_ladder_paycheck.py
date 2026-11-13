"""Chore rules v2: the weekly pay ladder in BankService.

< 60 % of the teen's covered chores completed → no pay for the week; 60–99 % →
the mode's existing per-task amount; 100 % → that amount plus +5/+10/+15 % by
early share (≥ 80/90/100 % before the 11:00 deadline). Applied only once the
week is final (Sunday's cutoff) and only in the parent-released modes.

Money: every expected amount below is a literal integer worked out by hand
(odd cap / point value so the integer floors actually bite), never re-derived
with the code under test.
"""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.bank_service import BankService
from app.services.early_bird_rules import week_ladder
from app.services.payout_receipt_service import record_receipt

MX = ZoneInfo("America/Mexico_City")
MODES = ("chore_proportional", "chore_gated", "points_rate")
CAP = 12345          # weekly cap for chore_proportional / chore_gated
POINTS = 7           # points per chore
POINT_VALUE = 113    # centavos per point (points_rate)

# Hand-computed per-task amounts for a 10-chore week (7 pts each).
#   chore_proportional: 12345 * done // 10   chore_gated: 12345 iff 10/10
#   points_rate: done * 7 pts * 113 c
FULL = {"chore_proportional": 12345, "chore_gated": 12345, "points_rate": 7910}
SIX = {"chore_proportional": 7407, "chore_gated": 0, "points_rate": 4746}
FIVE = {"chore_proportional": 6172, "chore_gated": 0, "points_rate": 3955}
# Bonus on FULL by early count: 5 % / 10 % / 15 %, floored.
BONUS = {
    "chore_proportional": {8: 617, 9: 1234, 10: 1851},
    "chore_gated": {8: 617, 9: 1234, 10: 1851},
    "points_rate": {8: 395, 9: 791, 10: 1186},
}
PCT = {8: 5, 9: 10, 10: 15}
# Mon..Sun spread of the 10 chores.
DAYS = (0, 0, 1, 1, 2, 2, 3, 4, 5, 6)


def _local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=MX).astimezone(timezone.utc)


def _this_monday() -> date:
    today = datetime.now(MX).date()
    return today - timedelta(days=today.weekday())


LAST = _this_monday() - timedelta(days=7)  # always final: its Sunday cutoff is past
LAST_SUN = LAST + timedelta(days=6)


async def _family(db, family, *, enabled=True):
    family.timezone = "America/Mexico_City"
    family.early_bird_enabled = enabled
    family.early_bird_enabled_at = datetime.now(timezone.utc) - timedelta(days=60)
    family.early_bird_deadline = time(11, 0)
    family.chore_cutoff = time(20, 30)
    family.grab_window_end = time(22, 30)
    family.early_bird_days = None
    family.point_value_cents = POINT_VALUE
    await db.commit()


async def _account(db, kid, mode):
    acct = await BankService.ensure_account(db, kid)
    acct.allowance_mode = mode
    acct.allowance_cents = 0 if mode == "points_rate" else CAP
    await db.commit()
    return acct


async def _chore(db, family, kid, day, *, hh=None, grade=None, exempt=False):
    """hh None = left open (PENDING); otherwise COMPLETED + APPROVED at hh:00."""
    t = TaskTemplate(id=uuid4(), title="Chore", points=POINTS, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                     early_bird_exempt=exempt, family_id=family.id)
    db.add(t)
    await db.flush()
    done = hh is not None
    db.add(TaskAssignment(
        family_id=family.id, template_id=t.id, assigned_to=kid.id, assigned_date=day,
        week_of=day - timedelta(days=day.weekday()),
        status=AssignmentStatus.COMPLETED if done else AssignmentStatus.PENDING,
        approval_status=ApprovalStatus.APPROVED if done else ApprovalStatus.NONE,
        completion_grade=grade,
        partial_credit_pct=50 if grade == "partial" else None,
        completed_at=_local(day, hh) if done else None,
    ))
    await db.commit()


async def _week(db, family, kid, monday, *, early, late=0, partial=0):
    """10 chores: `early` done 09:00 (before the 11:00 deadline), `late` done
    15:00 (after the deadline, before the 20:30 cutoff), `partial` done early
    but graded partial, the rest left open."""
    kinds = ["early"] * early + ["late"] * late + ["partial"] * partial
    kinds += ["open"] * (10 - len(kinds))
    for kind, offset in zip(kinds, DAYS):
        day = monday + timedelta(days=offset)
        if kind == "open":
            await _chore(db, family, kid, day)
        elif kind == "late":
            await _chore(db, family, kid, day, hh=15)
        else:
            await _chore(db, family, kid, day, hh=9,
                         grade="partial" if kind == "partial" else None)


async def _project(db, kid, family, monday=LAST, now=None):
    acct = await BankService.ensure_account(db, kid)
    return await BankService._paycheck_projection(db, acct, family.id, monday, now=now)


async def _allowance(db, kid):
    rows = (await db.execute(select(CashTransaction).where(
        CashTransaction.user_id == kid.id,
        CashTransaction.type == CashTransactionType.ALLOWANCE))).scalars().all()
    return sum(r.amount_cents for r in rows), rows


@pytest.fixture
async def ctx(db_session, test_family, test_teen_user):
    await _family(db_session, test_family)
    return db_session, test_family, test_teen_user


# ------------------------------------------------------------- pure helper

@pytest.mark.parametrize("amount,metrics,expected", [
    (1000, week_ladder(5, 5, 10), (0, 0, 0)),          # no_pay
    (1000, week_ladder(6, 6, 10), (1000, 0, 0)),       # per_task, exactly 60 %
    (1000, week_ladder(9, 9, 10), (1000, 0, 0)),       # per_task
    (1000, week_ladder(0, 0, 0), (1000, 0, 0)),        # neutral
    (12345, week_ladder(10, 7, 10), (12345, 0, 0)),    # 100 % but < 80 % early
    (12345, week_ladder(10, 8, 10), (12345, 617, 5)),
    (12345, week_ladder(10, 9, 10), (12345, 1234, 10)),
    (12345, week_ladder(10, 10, 10), (12345, 1851, 15)),
    (7910, week_ladder(10, 8, 10), (7910, 395, 5)),    # 395.5 floors
    (7910, week_ladder(10, 10, 10), (7910, 1186, 15)),  # 1186.5 floors
    (0, week_ladder(5, 5, 10), (0, 0, 0)),             # a zero never goes negative
    (0, week_ladder(10, 10, 10), (0, 0, 15)),
])
def test_ladder_adjust(amount, metrics, expected):
    assert BankService._ladder_adjust(amount, metrics) == expected


# ------------------------------------------------------- tiers, every mode

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_under_sixty_pays_nothing(ctx, mode):
    db, fam, kid = ctx
    await _account(db, kid, mode)
    await _week(db, fam, kid, LAST, early=5)
    p = await _project(db, kid, fam)
    assert p["amount_cents"] == 0
    assert p["early_bird_bonus_cents"] == 0 and p["early_bird_week_pct"] == 0
    assert p["ladder_tier"] == "no_pay" and p["ladder_final"] is True
    assert p["completed_pct"] == 50 and p["early_pct"] == 50


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sixty_pays_the_per_task_amount(ctx, mode):
    db, fam, kid = ctx
    await _account(db, kid, mode)
    await _week(db, fam, kid, LAST, early=6)
    p = await _project(db, kid, fam)
    assert p["amount_cents"] == SIX[mode]
    assert p["early_bird_bonus_cents"] == 0 and p["early_bird_week_pct"] == 0
    assert (p["ladder_tier"], p["completed_pct"]) == ("per_task", 60)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("early", [8, 9, 10])
async def test_full_week_pays_the_early_bonus(ctx, mode, early):
    db, fam, kid = ctx
    await _account(db, kid, mode)
    await _week(db, fam, kid, LAST, early=early, late=10 - early)
    p = await _project(db, kid, fam)
    assert p["early_bird_bonus_cents"] == BONUS[mode][early]
    assert p["amount_cents"] == FULL[mode] + BONUS[mode][early]
    assert p["early_bird_week_pct"] == PCT[early]
    assert (p["ladder_tier"], p["completed_pct"], p["early_pct"]) == ("bonus", 100, early * 10)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_full_week_under_eighty_early_has_no_bonus(ctx, mode):
    db, fam, kid = ctx
    await _account(db, kid, mode)
    await _week(db, fam, kid, LAST, early=7, late=3)
    p = await _project(db, kid, fam)
    assert p["amount_cents"] == FULL[mode]
    assert p["early_bird_bonus_cents"] == 0 and p["early_bird_week_pct"] == 0
    assert (p["ladder_tier"], p["early_pct"]) == ("bonus", 70)


@pytest.mark.asyncio
async def test_projection_ladder_fields_are_strict_types(ctx):
    db, fam, kid = ctx
    await _account(db, kid, "chore_proportional")
    await _week(db, fam, kid, LAST, early=9, late=1)
    p = await _project(db, kid, fam)
    for key in ("completed_pct", "early_pct", "early_bird_week_pct", "amount_cents",
                "early_bird_bonus_cents"):
        assert type(p[key]) is int, key
    assert type(p["ladder_final"]) is bool and isinstance(p["ladder_tier"], str)


# ------------------------------------------------- what the ladder leaves alone

@pytest.mark.asyncio
async def test_flat_mode_unaffected(ctx):
    db, fam, kid = ctx
    await _account(db, kid, "flat")
    await _week(db, fam, kid, LAST, early=5)
    p = await _project(db, kid, fam)
    assert p["amount_cents"] == 0 and p["early_bird_bonus_cents"] == 0
    assert p["ladder_tier"] == "neutral" and p["ladder_final"] is False
    with pytest.raises(HTTPException) as exc:
        await BankService.release_chore_paycheck(db, kid, fam.id, LAST, entitled=False)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_early_bird_off_pays_legacy_amounts(db_session, test_family, test_teen_user, mode):
    db, fam, kid = db_session, test_family, test_teen_user
    await _family(db, fam, enabled=False)
    await _account(db, kid, mode)
    await _week(db, fam, kid, LAST, early=5)
    p = await _project(db, kid, fam)
    assert p["amount_cents"] == FIVE[mode]  # not zeroed
    assert p["ladder_tier"] == "neutral"
    await _week(db, fam, kid, LAST - timedelta(days=7), early=10)
    p = await _project(db, kid, fam, LAST - timedelta(days=7))
    assert p["amount_cents"] == FULL[mode] and p["early_bird_bonus_cents"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_non_final_week_is_not_zeroed_and_has_no_bonus(ctx, mode):
    """Before Sunday's 20:30 cutoff the week can still change: the amount is the
    per-task one, the tier is exposed so the UI can show 'at risk'."""
    db, fam, kid = ctx
    await _account(db, kid, mode)
    await _week(db, fam, kid, LAST, early=5)
    before = datetime.combine(LAST_SUN, time(20, 29), tzinfo=MX)
    at_cutoff = datetime.combine(LAST_SUN, time(20, 30), tzinfo=MX)
    p = await _project(db, kid, fam, now=before)
    assert p["amount_cents"] == FIVE[mode]
    assert (p["ladder_tier"], p["ladder_final"], p["completed_pct"]) == ("no_pay", False, 50)
    p = await _project(db, kid, fam, now=at_cutoff)
    assert p["amount_cents"] == 0 and p["ladder_final"] is True


@pytest.mark.asyncio
async def test_non_final_full_week_has_no_bonus_yet(ctx):
    db, fam, kid = ctx
    await _account(db, kid, "chore_proportional")
    await _week(db, fam, kid, LAST, early=10)
    before = datetime.combine(LAST_SUN, time(20, 29), tzinfo=MX)
    p = await _project(db, kid, fam, now=before)
    assert p["amount_cents"] == 12345 and p["early_bird_bonus_cents"] == 0
    assert p["early_bird_week_pct"] == 0 and p["ladder_tier"] == "bonus"


@pytest.mark.asyncio
async def test_child_is_not_covered_so_pays_legacy(
        db_session, test_family, test_teen_user, test_parent_user, test_parent_user_2):
    """Exact mirror of the real family (2 parents + a teen + a child): Early Bird
    covers teens only, so in the same family the child's 5/10 week still pays
    per task while the teen's 5/10 week pays nothing."""
    db, fam, teen = db_session, test_family, test_teen_user
    await _family(db, fam)
    child = User(email="kid2@test.com", password_hash=get_password_hash("password123"),
                 name="Test Child", role=UserRole.CHILD, family_id=fam.id,
                 email_verified=True, points=0)
    db.add(child)
    await db.commit()
    for kid in (teen, child):
        await _account(db, kid, "chore_proportional")
        await _week(db, fam, kid, LAST, early=5)
    assert (await _project(db, teen, fam))["amount_cents"] == 0
    p = await _project(db, child, fam)
    assert p["amount_cents"] == 6172 and p["ladder_tier"] == "neutral"


@pytest.mark.asyncio
async def test_other_familys_rows_do_not_move_the_ladder(ctx, db_session):
    """Family scoping: a second family's teen with a perfect week does not lift
    this teen out of no_pay."""
    from app.models.family import Family

    db, fam, kid = ctx
    await _account(db, kid, "chore_proportional")
    await _week(db, fam, kid, LAST, early=5)
    other = Family(name="Other")
    db.add(other)
    await db.commit()
    await _family(db, other)
    teen2 = User(email="teen2@test.com", password_hash=get_password_hash("password123"),
                 name="Other Teen", role=UserRole.TEEN, family_id=other.id,
                 email_verified=True, points=0)
    db.add(teen2)
    await db.commit()
    await _week(db, other, teen2, LAST, early=10)
    assert (await _project(db, kid, fam))["amount_cents"] == 0


# --------------------------------------------------- release / top-up / receipt

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("early,late", [(5, 0), (6, 0), (9, 1), (7, 3)])
async def test_release_pays_exactly_the_projection(ctx, mode, early, late):
    db, fam, kid = ctx
    await _account(db, kid, mode)
    await _week(db, fam, kid, LAST, early=early, late=late)
    projected = (await _project(db, kid, fam))["amount_cents"]
    preview = await BankService.chore_paycheck_preview(db, kid, fam.id, LAST)
    assert preview["projected_cents"] == projected
    r = await BankService.release_chore_paycheck(db, kid, fam.id, LAST, entitled=False)
    assert r["amount_cents"] == projected
    total, rows = await _allowance(db, kid)
    assert total == projected and len(rows) >= 1  # a $0 week still leaves its row
    labelled = any("+10% madrugador" in (x.description or "") for x in rows)
    assert labelled == (early == 9)  # (7, 3) is 100 % but under 80 % early: no bonus


@pytest.mark.asyncio
async def test_release_no_pay_week_marks_it_handled(ctx):
    db, fam, kid = ctx
    await _account(db, kid, "chore_proportional")
    await _week(db, fam, kid, LAST, early=5)
    await BankService.release_chore_paycheck(db, kid, fam.id, LAST, entitled=False)
    weeks = await BankService.list_outstanding_weeks(db, kid, fam.id)
    assert LAST not in {w["week_of"] for w in weeks}


@pytest.mark.asyncio
async def test_top_up_still_pays_the_typed_amount(ctx):
    db, fam, kid = ctx
    await _account(db, kid, "chore_proportional")
    await _week(db, fam, kid, LAST, early=5)
    first = await BankService.release_chore_paycheck(db, kid, fam.id, LAST, entitled=False)
    assert first["amount_cents"] == 0
    r = await BankService.release_chore_paycheck(
        db, kid, fam.id, LAST, entitled=False, adjustment_cents=5000, top_up=True)
    assert r["amount_cents"] == 5000
    assert (await _allowance(db, kid))[0] == 5000


@pytest.mark.asyncio
@pytest.mark.parametrize("early,receipt", [(5, 3000), (10, 9999), (10, 14196)])
async def test_receipt_confirm_pays_the_receipt_amount(ctx, test_parent_user, early, receipt):
    """The ladder only moves the base the adjustment is measured against: the
    kid is credited exactly the receipt (14196 = 12345 + 1851, adjustment 0)."""
    db, fam, kid = ctx
    await _account(db, kid, "chore_proportional")
    await _week(db, fam, kid, LAST, early=early)
    await record_receipt(
        db, kid, fam.id, folio=f"F-LAD-{early}-{receipt}", receipt_date=None, concept="",
        amount_cents=receipt, allocations=[{"week_of": LAST, "amount_cents": receipt}],
        released_by=test_parent_user.id,
    )
    total, rows = await _allowance(db, kid)
    assert total == receipt and len(rows) == 1


@pytest.mark.asyncio
async def test_early_bird_bonus_derives_from_the_ladder(ctx):
    db, fam, kid = ctx
    await _week(db, fam, kid, LAST, early=10)
    assert await BankService._early_bird_bonus(db, fam.id, kid.id, LAST, 12345) == (1851, 15)
    await _week(db, fam, kid, LAST - timedelta(days=7), early=7, late=3)
    assert await BankService._early_bird_bonus(
        db, fam.id, kid.id, LAST - timedelta(days=7), 12345) == (0, 0)


# ------------------------------------------------------- chore_gated reconcile

@pytest.mark.asyncio
async def test_chore_gated_gate_and_floor_do_not_double_apply(ctx):
    """Gate (0 unless 10/10 at full credit) then floor (0 under 60 %): the same
    zero, never negative, and the release writes a $0 row."""
    db, fam, kid = ctx
    await _account(db, kid, "chore_gated")
    await _week(db, fam, kid, LAST, early=5)
    p = await _project(db, kid, fam)
    assert (p["amount_cents"], p["early_bird_bonus_cents"], p["ladder_tier"]) == (0, 0, "no_pay")
    r = await BankService.release_chore_paycheck(db, kid, fam.id, LAST, entitled=False)
    assert r["amount_cents"] == 0
    total, rows = await _allowance(db, kid)
    assert total == 0 and len(rows) == 1 and rows[0].amount_cents == 0


@pytest.mark.asyncio
async def test_chore_gated_partial_grade_fails_gate_without_bonus(ctx):
    """One partial grade: the gate pays 0 and the ladder sees 9/10 (partial is
    not completed) — 0, not a bonus on top of a closed gate."""
    db, fam, kid = ctx
    await _account(db, kid, "chore_gated")
    await _week(db, fam, kid, LAST, early=9, partial=1)
    p = await _project(db, kid, fam)
    assert (p["amount_cents"], p["early_bird_bonus_cents"], p["ladder_tier"]) == (0, 0, "per_task")


@pytest.mark.asyncio
async def test_chore_gated_closed_gate_under_a_perfect_ladder_pays_nothing(ctx):
    """An undone "evening" (early_bird_exempt) chore closes the gate but is not
    covered, so the ladder still reads 10/10 all early (+15 %): 15 % of a closed
    gate is 0, and the week must not be labelled with a % it did not pay."""
    db, fam, kid = ctx
    await _account(db, kid, "chore_gated")
    await _week(db, fam, kid, LAST, early=10)
    await _chore(db, fam, kid, LAST, exempt=True)  # left open
    p = await _project(db, kid, fam)
    assert (p["ladder_tier"], p["early_pct"]) == ("bonus", 100)
    assert (p["amount_cents"], p["early_bird_bonus_cents"], p["early_bird_week_pct"]) == (0, 0, 0)
    r = await BankService.release_chore_paycheck(db, kid, fam.id, LAST, entitled=False)
    assert r["amount_cents"] == 0
    _, rows = await _allowance(db, kid)
    assert not any("madrugador" in (x.description or "") for x in rows)


# ------------------------------------------------------- multi-week surfaces

@pytest.mark.asyncio
async def test_outstanding_weeks_carry_the_ladder(ctx):
    db, fam, kid = ctx
    await _account(db, kid, "points_rate")
    await _week(db, fam, kid, LAST, early=9, late=1)
    await _week(db, fam, kid, LAST - timedelta(days=7), early=5)
    weeks = {w["week_of"]: w for w in await BankService.list_outstanding_weeks(db, kid, fam.id)}
    w = weeks[LAST]
    assert (w["amount_cents"], w["early_bird_bonus_cents"], w["early_bird_week_pct"]) == (
        7910 + 791, 791, 10)
    assert weeks[LAST - timedelta(days=7)]["amount_cents"] == 0
