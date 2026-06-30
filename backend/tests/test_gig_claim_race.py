"""Concurrency / double-award protection for gig claims.

Two parents (or two browser tabs) approving the same COMPLETED claim at the
same time must award points exactly once. Without a row lock both calls read
status=COMPLETED, both award, and two PointTransaction rows are written.
"""
import asyncio

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.gig import GigOffering, GigClaim, GigClaimStatus
from app.models.cash_transaction import CashTransaction
from app.services.gig_claim_service import GigClaimService
from app.core.exceptions import ValidationException


async def _completed_claim(db, family, parent, child, points=25):
    offering = GigOffering(
        family_id=family.id, title="Wash car", points=points, created_by=parent.id,
    )
    db.add(offering)
    await db.flush()
    claim = GigClaim(
        gig_id=offering.id, family_id=family.id,
        claimed_by=child.id, status=GigClaimStatus.COMPLETED,
    )
    db.add(claim)
    await db.commit()
    return claim


@pytest.mark.asyncio
async def test_concurrent_approve_awards_points_once(
    test_engine, db_session, test_family, test_parent_user, test_child_user
):
    claim = await _completed_claim(
        db_session, test_family, test_parent_user, test_child_user, points=25
    )
    claim_id = claim.id
    points_before = test_child_user.points
    cash_before = test_child_user.cash_cents
    streak_before = test_child_user.gig_trust_streak

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _approve():
        async with maker() as s:
            return await GigClaimService.approve(
                s, claim_id, test_parent_user.id, test_family.id,
                approved=True, notes=None,
            )

    results = await asyncio.gather(_approve(), _approve(), return_exceptions=True)

    succeeded = [r for r in results if isinstance(r, GigClaim)]
    failed = [r for r in results if isinstance(r, Exception)]
    assert len(succeeded) == 1, f"expected 1 success, got {results}"
    assert len(failed) == 1 and isinstance(failed[0], ValidationException), (
        f"expected 1 ValidationException, got {results}"
    )

    # Cash credited exactly once.
    txn_count = await db_session.scalar(
        select(func.count())
        .select_from(CashTransaction)
        .where(CashTransaction.gig_claim_id == claim_id)
    )
    assert txn_count == 1, f"double-award: {txn_count} cash transactions"

    await db_session.refresh(test_child_user)
    assert test_child_user.cash_cents == cash_before + 2500  # $25 → 2500 cents
    assert test_child_user.points == points_before           # gigs don't touch points
    assert test_child_user.gig_trust_streak == streak_before + 1


@pytest.mark.asyncio
async def test_concurrent_complete_auto_approve_awards_once(
    test_engine, db_session, test_family, test_parent_user, test_child_user
):
    """Trusted-kid auto-approve path: two concurrent proof submissions on the
    same CLAIMED claim must auto-approve and award points only once."""
    from app.core.config import settings

    # Make the child trusted so complete() takes the auto-approve branch.
    test_child_user.gig_trust_streak = max(1, settings.GIG_AUTO_APPROVE_STREAK)
    offering = GigOffering(
        family_id=test_family.id, title="Sweep", points=15,
        created_by=test_parent_user.id,
    )
    db_session.add(offering)
    await db_session.flush()
    claim = GigClaim(
        gig_id=offering.id, family_id=test_family.id,
        claimed_by=test_child_user.id, status=GigClaimStatus.CLAIMED,
    )
    db_session.add(claim)
    await db_session.commit()
    claim_id = claim.id

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _complete():
        async with maker() as s:
            return await GigClaimService.complete(
                s, claim_id, test_child_user.id, proof_text="done",
            )

    results = await asyncio.gather(_complete(), _complete(), return_exceptions=True)

    failed = [r for r in results if isinstance(r, Exception)]
    assert len(failed) == 1 and isinstance(failed[0], ValidationException), (
        f"expected 1 ValidationException, got {results}"
    )

    txn_count = await db_session.scalar(
        select(func.count())
        .select_from(CashTransaction)
        .where(CashTransaction.gig_claim_id == claim_id)
    )
    assert txn_count == 1, f"double-award: {txn_count} cash transactions"
