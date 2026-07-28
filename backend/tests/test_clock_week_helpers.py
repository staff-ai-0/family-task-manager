"""The tests' week helpers must name the same week the money path names.

Regression guard for a flake class that has now been root-caused three times
(commits 6a78b74, 170057c, and the admin money tests added with PR #163):
a test builds `week_of` from the runner's `date.today()`, while BankService
resolves "this week" from `_family_local_today` — the family's timezone. When
the two clocks are on different calendar days the seeded, money-bearing row
lands in a bucket the paycheck math never looks at, the payout comes out $0
and the assertion fails for reasons that have nothing to do with the code
under test.

These tests pin `conftest.current_week_monday` to the service's own answer, in
timezones far enough from any runner to make the divergence real.
"""
from datetime import date, timedelta
from uuid import uuid4

import pytest

from app.models.family import Family
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import APPROVAL_APPROVED, User, UserRole
from app.services.bank_service import BankService
from conftest import current_week_monday, family_local_today

# 25 hours apart — wider than a calendar day, so these two families are NEVER
# on the same date as each other, which makes "at least one of them disagrees
# with the runner's date" a fact rather than a hope (see the first test).
EAST = "Pacific/Kiritimati"   # UTC+14
WEST = "Pacific/Pago_Pago"    # UTC-11


async def _family(db, tz):
    fam = Family(name=f"Fam {tz}", timezone=tz)
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


async def _kid(db, fam):
    u = User(
        email=f"u{uuid4().hex[:10]}@t.com", name="T", role=UserRole.TEEN,
        family_id=fam.id, email_verified=True, cash_cents=0, points=0,
        approval_status=APPROVAL_APPROVED, is_active=True, preferred_lang="es",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _completed_chore(db, fam, kid, points, week):
    t = TaskTemplate(
        title="C", points=points, effort_level=1, interval_days=1, is_bonus=False,
        assignment_type=AssignmentType.AUTO, family_id=fam.id,
    )
    db.add(t)
    await db.flush()
    db.add(TaskAssignment(
        template_id=t.id, assigned_to=kid.id, family_id=fam.id,
        status=AssignmentStatus.COMPLETED, approval_status=ApprovalStatus.APPROVED,
        assigned_date=week, week_of=week,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_family_local_today_can_differ_from_the_runner_clock(db):
    """Proves the guard below is not vacuous.

    The two zones are 25 h apart, so their local dates always differ from each
    other; at most one of them can equal the runner's `date.today()`. A test
    that derives dates from the runner clock is therefore guaranteed to be
    wrong for at least one of these families, right now, on any machine.
    """
    east = await _family(db, EAST)
    west = await _family(db, WEST)

    east_today = await family_local_today(db, east.id)
    west_today = await family_local_today(db, west.id)
    runner_today = date.today()

    assert east_today != west_today
    assert not (east_today == runner_today and west_today == runner_today)


@pytest.mark.asyncio
@pytest.mark.parametrize("tz", [EAST, WEST])
async def test_current_week_monday_is_the_week_the_paycheck_math_uses(db, tz):
    """`chore_paycheck_preview` with no explicit week_of picks the week itself,
    from the family's clock. A chore filed in `current_week_monday`'s bucket
    must be the one it counts — that equality IS the helper's contract."""
    fam = await _family(db, tz)
    kid = await _kid(db, fam)
    acct = await BankService.ensure_account(db, kid)
    acct.allowance_mode = "chore_proportional"
    acct.allowance_cents = 20000
    await db.commit()

    week = await current_week_monday(db, fam.id)
    await _completed_chore(db, fam, kid, 10, week)

    preview = await BankService.chore_paycheck_preview(db, kid, fam.id)
    assert preview["week_of"] == week
    assert preview["done_points"] == 10
    assert preview["assigned_points"] == 10
    assert preview["projected_cents"] == 20000  # 100 % of the cap


@pytest.mark.asyncio
@pytest.mark.parametrize("tz", [EAST, WEST])
async def test_runner_clock_week_can_miss_the_money_row_entirely(db, tz):
    """The failure mode itself, demonstrated: when the runner's week Monday is
    not the family's, that bucket holds nothing — a paycheck keyed to it pays
    $0 while the family's own week is fully earned. Asserted only when the two
    weeks actually differ (they do on the UTC-6 dev box every Sunday evening,
    and for one of these two zones for most of every day)."""
    fam = await _family(db, tz)
    kid = await _kid(db, fam)
    week = await current_week_monday(db, fam.id)
    await _completed_chore(db, fam, kid, 10, week)

    runner_today = date.today()
    runner_week = runner_today - timedelta(days=runner_today.weekday())
    if runner_week == week:
        pytest.skip("runner clock happens to agree with this family's week")

    done, assigned, _ = await BankService._chore_units(db, fam.id, kid.id, runner_week)
    assert (done, assigned) == (0, 0)
