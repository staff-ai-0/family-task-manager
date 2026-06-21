"""M12: deleting a family must cascade to its members and invitations.

delete_family() documents "cascade to all related data" but the FKs had no
ondelete and the members/invitations relationships had no ORM cascade, so a
delete on any non-empty family raised an IntegrityError (or orphaned rows).
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, func

from app.models.family import Family
from app.models.user import User, UserRole
from app.models.invitation import FamilyInvitation, InvitationStatus
from app.models.point_transaction import PointTransaction, TransactionType
from app.services.family_service import FamilyService


@pytest.mark.asyncio
async def test_delete_family_cascades_members_and_invitations(
    db_session, test_family, test_parent_user, test_child_user
):
    inv = FamilyInvitation(
        family_id=test_family.id,
        invited_email="newkid@test.com",
        invited_by_user_id=test_parent_user.id,
        invitation_code=FamilyInvitation.generate_code(),
        status=InvitationStatus.PENDING,
        role=UserRole.CHILD,
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    db_session.add(inv)

    # A user-owned row exercises the recursive User -> children cascade.
    txn = PointTransaction(
        user_id=test_child_user.id,
        type=TransactionType.BONUS,
        points=10,
        balance_before=0,
        balance_after=10,
        description="seed",
    )
    db_session.add(txn)
    await db_session.commit()

    fam_id = test_family.id

    await FamilyService.delete_family(db_session, fam_id)

    assert await db_session.get(Family, fam_id) is None

    users_left = (
        await db_session.execute(
            select(func.count()).select_from(User).where(User.family_id == fam_id)
        )
    ).scalar()
    assert users_left == 0, "members must be deleted with the family"

    inv_left = (
        await db_session.execute(
            select(func.count())
            .select_from(FamilyInvitation)
            .where(FamilyInvitation.family_id == fam_id)
        )
    ).scalar()
    assert inv_left == 0, "invitations must be deleted with the family"

    txn_left = (
        await db_session.execute(
            select(func.count())
            .select_from(PointTransaction)
            .where(PointTransaction.user_id == test_child_user.id)
        )
    ).scalar()
    assert txn_left == 0, "member-owned rows must cascade with the family"
