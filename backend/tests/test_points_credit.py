"""PointsService credit helpers: the locked balance read every award shares."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.point_transaction import PointTransaction, TransactionType
from app.models.user import User
from app.services.points_service import PointsService


def _prod_like(test_engine):
    # Production sessions: expire_on_commit=False AND autoflush=False.
    return async_sessionmaker(test_engine, class_=AsyncSession,
                              expire_on_commit=False, autoflush=False)


@pytest.mark.asyncio
async def test_award_reads_the_balance_under_the_lock_not_the_identity_map(
    db_session, test_family, test_child_user, test_engine,
):
    """The request's user object can carry an old balance (loaded before
    another transaction changed it); the credit must start from the DB."""
    kid_id, fam_id = test_child_user.id, test_family.id
    async with _prod_like(test_engine)() as s:
        kid = (await s.execute(select(User).where(User.id == kid_id))).scalar_one()
        stale = int(kid.points)
        await s.commit()
        async with _prod_like(test_engine)() as other:
            await other.execute(text("UPDATE users SET points = points + 40 WHERE id = :i"), {"i": kid_id})
            await other.commit()
        tx = await PointsService.award_bonus_points(s, kid_id, fam_id, 5, "bonus")
        await s.commit()
        assert tx.balance_before == stale + 40
        assert tx.balance_after == stale + 45
    await db_session.refresh(test_child_user)
    assert test_child_user.points == stale + 45


@pytest.mark.asyncio
async def test_two_awards_in_one_transaction_both_land(
    db_session, test_family, test_child_user, test_engine,
):
    """approve_gig credits the chore and then the Early Bird bonus before one
    commit; with autoflush off the second read must keep the first credit."""
    kid_id, fam_id = test_child_user.id, test_family.id
    start = int(test_child_user.points)
    async with _prod_like(test_engine)() as s:
        await PointsService.award_assignment_completion(s, kid_id, fam_id, None, 10)
        second = await PointsService.award_bonus_points(s, kid_id, fam_id, 2, "bonus")
        await s.commit()
        assert second.balance_before == start + 10
    await db_session.refresh(test_child_user)
    assert test_child_user.points == start + 12
    rows = (await db_session.execute(select(PointTransaction).where(
        PointTransaction.user_id == kid_id))).scalars().all()
    assert sorted(r.type for r in rows) == sorted([TransactionType.TASK_COMPLETED, TransactionType.BONUS])
