"""Tenancy of the points ledger.

point_transactions carries its own family_id, so PointsService no longer has to
trust that the caller resolved the user through get_family_user first. These
tests pin the two halves of that: every write stamps the owning family, and
every aggregate refuses to answer for a user outside the family it was asked
about (before family_id existed those aggregates keyed on user_id alone and
happily returned the other family's totals).
"""

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.exceptions import NotFoundException
from app.models.family import Family
from app.models.point_transaction import PointTransaction
from app.models.reward import Reward, RewardCategory
from app.models.user import User, UserRole
from app.schemas.points import ParentAdjustment, PointTransfer
from app.services.points_service import PointsService
from app.services.reward_service import RewardService


async def _family(db, name, email_prefix):
    fam = Family(name=name)
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    kid = User(
        email=f"{email_prefix}-kid@test.com",
        name=f"{name} Kid",
        role=UserRole.CHILD,
        family_id=fam.id,
        email_verified=True,
        points=0,
    )
    parent = User(
        email=f"{email_prefix}-parent@test.com",
        name=f"{name} Parent",
        role=UserRole.PARENT,
        family_id=fam.id,
        email_verified=True,
        points=0,
    )
    db.add_all([kid, parent])
    await db.commit()
    await db.refresh(kid)
    await db.refresh(parent)
    return fam, kid, parent


@pytest_asyncio.fixture
async def two_families(db_session):
    """Two fully independent families, each with a kid and a parent."""
    alpha = await _family(db_session, "Alpha", "alpha")
    beta = await _family(db_session, "Beta", "beta")
    return alpha, beta


@pytest.mark.asyncio
async def test_awards_stamp_the_owning_family(db_session, two_families):
    (fam_a, kid_a, _), (fam_b, kid_b, _) = two_families

    await PointsService.award_points_for_task(db_session, kid_a.id, fam_a.id, 50)
    await PointsService.award_points_for_task(db_session, kid_b.id, fam_b.id, 70)

    rows = (
        await db_session.execute(
            select(PointTransaction.user_id, PointTransaction.family_id)
        )
    ).all()
    assert set(rows) == {(kid_a.id, fam_a.id), (kid_b.id, fam_b.id)}


@pytest.mark.asyncio
async def test_totals_never_include_another_familys_rows(db_session, two_families):
    (fam_a, kid_a, _), (fam_b, kid_b, _) = two_families

    await PointsService.award_points_for_task(db_session, kid_a.id, fam_a.id, 50)
    await PointsService.award_points_for_task(db_session, kid_b.id, fam_b.id, 900)

    # Alpha asking about its own kid sees only its own award.
    assert await PointsService.get_total_earned(db_session, kid_a.id, fam_a.id) == 50

    # Alpha guessing Beta's kid id gets nothing — the family predicate, not the
    # caller, is what stops the read.
    assert await PointsService.get_total_earned(db_session, kid_b.id, fam_a.id) == 0
    assert await PointsService.get_transaction_history(
        db_session, kid_b.id, fam_a.id
    ) == []
    with pytest.raises(NotFoundException):
        await PointsService.get_points_summary(db_session, kid_b.id, fam_a.id)

    # And the ledger really does hold Beta's 900 — the zero above is scoping,
    # not an empty table.
    beta_total = (
        await db_session.execute(
            select(func.sum(PointTransaction.points)).where(
                PointTransaction.family_id == fam_b.id
            )
        )
    ).scalar()
    assert beta_total == 900


@pytest.mark.asyncio
async def test_spend_totals_are_family_scoped(
    db_session, two_families
):
    (fam_a, kid_a, _), (fam_b, kid_b, _) = two_families

    reward_b = Reward(
        family_id=fam_b.id,
        title="Beta reward",
        points_cost=40,
        category=RewardCategory.TREATS,
    )
    db_session.add(reward_b)
    kid_b.points = 100
    await db_session.commit()
    await db_session.refresh(reward_b)

    await PointsService.deduct_points_for_reward(
        db=db_session,
        user_id=kid_b.id,
        family_id=fam_b.id,
        reward_id=reward_b.id,
        points_cost=40,
    )

    assert await PointsService.get_total_spent(db_session, kid_b.id, fam_b.id) == 40
    assert await PointsService.get_total_spent(db_session, kid_b.id, fam_a.id) == 0
    assert await PointsService.get_total_spent(db_session, kid_a.id, fam_a.id) == 0

    # Redemption counts key off the same ledger and must scope the same way.
    assert await RewardService.get_user_redemption_count(
        db_session, kid_b.id, reward_b.id, fam_b.id
    ) == 1
    assert await RewardService.get_user_redemption_count(
        db_session, kid_b.id, reward_b.id, fam_a.id
    ) == 0


@pytest.mark.asyncio
async def test_award_across_families_is_refused_and_writes_nothing(
    db_session, two_families
):
    (fam_a, _, _), (_, kid_b, _) = two_families

    with pytest.raises(NotFoundException):
        await PointsService.award_points_for_task(db_session, kid_b.id, fam_a.id, 500)

    await db_session.refresh(kid_b)
    assert kid_b.points == 0
    ledger_rows = (
        await db_session.execute(select(func.count()).select_from(PointTransaction))
    ).scalar()
    assert ledger_rows == 0


@pytest.mark.asyncio
async def test_adjustment_and_transfer_stamp_the_caller_family(
    db_session, two_families
):
    (fam_a, kid_a, parent_a), _ = two_families
    kid_a.points = 60
    await db_session.commit()

    adjustment = await PointsService.create_parent_adjustment(
        db_session,
        ParentAdjustment(user_id=kid_a.id, points=10, reason="Helped a neighbor"),
        parent_id=parent_a.id,
        family_id=fam_a.id,
    )
    assert adjustment.family_id == fam_a.id

    debit, credit = await PointsService.transfer_points(
        db_session,
        PointTransfer(from_user_id=kid_a.id, to_user_id=parent_a.id, points=20),
        family_id=fam_a.id,
    )
    assert debit.family_id == fam_a.id
    assert credit.family_id == fam_a.id
