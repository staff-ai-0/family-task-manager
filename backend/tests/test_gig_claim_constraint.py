"""gig_claims partial-unique constraint.

The deployed migration creates a PARTIAL unique index
(uq_gig_claim_active ON gig_claims (gig_id, claimed_by) WHERE status != 'rejected'):
one ACTIVE (non-rejected) claim per user per gig, but a REJECTED claim must not
block re-claiming the same gig. The ORM declaration must match so that
Base.metadata.create_all (used by the test DB) enforces the same rule as prod.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.gig import GigOffering, GigClaim, GigClaimStatus


async def _offering(db, family_id, created_by):
    o = GigOffering(
        family_id=family_id, title="Wash car", points=10, created_by=created_by
    )
    db.add(o)
    await db.flush()
    return o


@pytest.mark.asyncio
async def test_reclaim_allowed_after_rejection(
    db_session, test_family, test_child_user, test_parent_user
):
    """A REJECTED claim must NOT block a fresh claim on the same gig+user."""
    offering = await _offering(db_session, test_family.id, test_parent_user.id)

    rejected = GigClaim(
        gig_id=offering.id, family_id=test_family.id,
        claimed_by=test_child_user.id, status=GigClaimStatus.REJECTED,
    )
    db_session.add(rejected)
    await db_session.commit()

    fresh = GigClaim(
        gig_id=offering.id, family_id=test_family.id,
        claimed_by=test_child_user.id, status=GigClaimStatus.CLAIMED,
    )
    db_session.add(fresh)
    await db_session.commit()  # must NOT raise — prior claim is rejected

    await db_session.refresh(fresh)
    assert fresh.status == GigClaimStatus.CLAIMED


@pytest.mark.asyncio
async def test_two_active_claims_forbidden(
    db_session, test_family, test_child_user, test_parent_user
):
    """Two non-rejected claims on the same gig+user must violate uniqueness."""
    offering = await _offering(db_session, test_family.id, test_parent_user.id)

    first = GigClaim(
        gig_id=offering.id, family_id=test_family.id,
        claimed_by=test_child_user.id, status=GigClaimStatus.CLAIMED,
    )
    db_session.add(first)
    await db_session.commit()

    second = GigClaim(
        gig_id=offering.id, family_id=test_family.id,
        claimed_by=test_child_user.id, status=GigClaimStatus.COMPLETED,
    )
    db_session.add(second)
    with pytest.raises(IntegrityError):
        await db_session.commit()
