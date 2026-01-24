"""
Tests for PointsService - Point Transfers and Parent Adjustments

Covers:
- Point transfers between users
- Parent manual adjustments
- Transaction history
"""

import pytest
from uuid import uuid4

from app.services.points_service import PointsService
from app.schemas.points import PointTransfer, ParentAdjustment
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ForbiddenException,
)


@pytest.mark.asyncio
class TestPointTransfers:
    """Test point transfer functionality"""

    async def test_transfer_points_successfully(
        self, db_session, test_parent_user, test_child_user, test_family
    ):
        """Test successful point transfer between users"""
        # Reset child points to 0 and give parent some points to transfer
        test_child_user.points = 0
        test_parent_user.points = 100
        await db_session.commit()

        transfer = PointTransfer(
            from_user_id=test_parent_user.id,
            to_user_id=test_child_user.id,
            points=50,
            reason="Helping with chores",
        )

        debit_txn, credit_txn = await PointsService.transfer_points(
            db_session, transfer, test_family.id
        )

        # Verify debit transaction
        assert debit_txn is not None
        assert debit_txn.user_id == test_parent_user.id
        assert debit_txn.points == -50
        assert debit_txn.balance_before == 100
        assert debit_txn.balance_after == 50

        # Verify credit transaction
        assert credit_txn is not None
        assert credit_txn.user_id == test_child_user.id
        assert credit_txn.points == 50
        assert credit_txn.balance_before == 0
        assert credit_txn.balance_after == 50

        # Verify balances updated
        await db_session.refresh(test_parent_user)
        await db_session.refresh(test_child_user)
        assert test_parent_user.points == 50
        assert test_child_user.points == 50

    async def test_transfer_insufficient_points(
        self, db_session, test_parent_user, test_child_user, test_family
    ):
        """Test transfer fails when user has insufficient points"""
        # Parent has 0 points
        assert test_parent_user.points == 0

        transfer = PointTransfer(
            from_user_id=test_parent_user.id,
            to_user_id=test_child_user.id,
            points=50,
        )

        with pytest.raises(ValidationException) as exc_info:
            await PointsService.transfer_points(db_session, transfer, test_family.id)

        assert "insufficient points" in str(exc_info.value).lower()

    async def test_transfer_to_nonexistent_user(
        self, db_session, test_parent_user, test_family
    ):
        """Test transfer to user that doesn't exist"""
        test_parent_user.points = 100
        await db_session.commit()

        transfer = PointTransfer(
            from_user_id=test_parent_user.id,
            to_user_id=uuid4(),  # Non-existent user
            points=50,
        )

        with pytest.raises(NotFoundException):
            await PointsService.transfer_points(db_session, transfer, test_family.id)

    async def test_transfer_from_nonexistent_user(
        self, db_session, test_child_user, test_family
    ):
        """Test transfer from user that doesn't exist"""
        transfer = PointTransfer(
            from_user_id=uuid4(),  # Non-existent user
            to_user_id=test_child_user.id,
            points=50,
        )

        with pytest.raises(NotFoundException):
            await PointsService.transfer_points(db_session, transfer, test_family.id)

    async def test_transfer_between_different_families(
        self, db_session, test_parent_user, test_family
    ):
        """Test transfer fails when users are in different families"""
        # Create another family and user
        from app.models import Family, User
        from app.models.user import UserRole
        
        other_family = Family(name="Other Family", is_active=True)
        db_session.add(other_family)
        await db_session.commit()
        await db_session.refresh(other_family)

        other_user = User(
            email="other@example.com",
            name="Other User",
            password_hash="hashed",
            role=UserRole.CHILD,
            family_id=other_family.id,
            points=0,
            is_active=True,
        )
        db_session.add(other_user)
        await db_session.commit()
        await db_session.refresh(other_user)

        test_parent_user.points = 100
        await db_session.commit()

        transfer = PointTransfer(
            from_user_id=test_parent_user.id,
            to_user_id=other_user.id,
            points=50,
        )

        # Using test_family.id means other_user won't be found (different family)
        with pytest.raises((ForbiddenException, NotFoundException)):
            await PointsService.transfer_points(
                db_session, transfer, test_family.id
            )
        db_session.add(other_user)
        await db_session.commit()
        await db_session.refresh(other_user)

        test_parent_user.points = 100
        await db_session.commit()

        transfer = PointTransfer(
            from_user_id=test_parent_user.id,
            to_user_id=other_user.id,
            points=50,
        )

        with pytest.raises((ForbiddenException, NotFoundException)):
            await PointsService.transfer_points(db_session, transfer, test_family.id)

    async def test_transfer_without_reason(
        self, db_session, test_parent_user, test_child_user, test_family
    ):
        """Test transfer without providing a reason"""
        test_parent_user.points = 100
        await db_session.commit()

        transfer = PointTransfer(
            from_user_id=test_parent_user.id,
            to_user_id=test_child_user.id,
            points=30,
            reason=None,
        )

        debit_txn, credit_txn = await PointsService.transfer_points(
            db_session, transfer, test_family.id
        )

        assert "Point transfer" in debit_txn.description
        assert "Point transfer" in credit_txn.description

    async def test_transfer_exact_balance(
        self, db_session, test_parent_user, test_child_user, test_family
    ):
        """Test transferring exact balance (all points)"""
        test_parent_user.points = 75
        test_child_user.points = 0  # Reset to 0
        await db_session.commit()

        transfer = PointTransfer(
            from_user_id=test_parent_user.id,
            to_user_id=test_child_user.id,
            points=75,
        )

        debit_txn, credit_txn = await PointsService.transfer_points(
            db_session, transfer, test_family.id
        )

        await db_session.refresh(test_parent_user)
        await db_session.refresh(test_child_user)

        assert test_parent_user.points == 0
        assert test_child_user.points == 75


@pytest.mark.asyncio
class TestParentAdjustments:
    """Test parent manual point adjustments"""

    async def test_parent_adjustment_add_points(
        self, db_session, test_parent_user, test_child_user, test_family
    ):
        """Test parent adding points to child"""
        initial_points = test_child_user.points

        adjustment = ParentAdjustment(
            user_id=test_child_user.id,
            points=50,
            reason="Good behavior this week",
        )

        transaction = await PointsService.create_parent_adjustment(
            db_session, adjustment, test_parent_user.id, test_family.id
        )

        assert transaction is not None
        assert transaction.user_id == test_child_user.id
        assert transaction.points == 50
        assert transaction.balance_before == initial_points
        assert transaction.balance_after == initial_points + 50

        await db_session.refresh(test_child_user)
        assert test_child_user.points == initial_points + 50

    async def test_parent_adjustment_deduct_points(
        self, db_session, test_parent_user, test_child_user, test_family
    ):
        """Test parent deducting points from child"""
        test_child_user.points = 100
        await db_session.commit()

        adjustment = ParentAdjustment(
            user_id=test_child_user.id,
            points=-30,
            reason="Breaking house rules",
        )

        transaction = await PointsService.create_parent_adjustment(
            db_session, adjustment, test_parent_user.id, test_family.id
        )

        assert transaction.points == -30
        assert transaction.balance_before == 100
        assert transaction.balance_after == 70

        await db_session.refresh(test_child_user)
        assert test_child_user.points == 70

    async def test_parent_adjustment_prevent_negative_balance(
        self, db_session, test_parent_user, test_child_user, test_family
    ):
        """Test that deducting more than balance doesn't go negative"""
        test_child_user.points = 20
        await db_session.commit()

        adjustment = ParentAdjustment(
            user_id=test_child_user.id,
            points=-50,  # More than they have
            reason="Major infraction",
        )

        transaction = await PointsService.create_parent_adjustment(
            db_session, adjustment, test_parent_user.id, test_family.id
        )

        await db_session.refresh(test_child_user)
        assert test_child_user.points == 0  # Should not go negative

    async def test_parent_adjustment_nonexistent_child(
        self, db_session, test_parent_user, test_family
    ):
        """Test adjustment for non-existent user"""
        adjustment = ParentAdjustment(
            user_id=uuid4(),
            points=50,
            reason="Test",
        )

        with pytest.raises(NotFoundException):
            await PointsService.create_parent_adjustment(
                db_session, adjustment, test_parent_user.id, test_family.id
            )

    async def test_parent_adjustment_nonexistent_parent(
        self, db_session, test_child_user, test_family
    ):
        """Test adjustment by non-existent parent"""
        adjustment = ParentAdjustment(
            user_id=test_child_user.id,
            points=50,
            reason="Test",
        )

        with pytest.raises(NotFoundException):
            await PointsService.create_parent_adjustment(
                db_session, adjustment, uuid4(), test_family.id
            )

    async def test_parent_adjustment_different_family(
        self, db_session, test_parent_user, test_child_user
    ):
        """Test adjustment fails for users in different family"""
        # Use wrong family ID
        adjustment = ParentAdjustment(
            user_id=test_child_user.id,
            points=50,
            reason="Test",
        )

        # Using wrong family_id will cause verification to fail
        with pytest.raises((ForbiddenException, NotFoundException)):
            await PointsService.create_parent_adjustment(
                db_session, adjustment, test_parent_user.id, uuid4()
            )


@pytest.mark.asyncio
class TestTransactionHistory:
    """Test transaction history retrieval"""

    async def test_get_empty_transaction_history(self, db_session, test_child_user):
        """Test getting history for user with no transactions"""
        history = await PointsService.get_transaction_history(
            db_session, test_child_user.id
        )

        assert history == []

    async def test_get_transaction_history_with_transactions(
        self, db_session, test_child_user, test_task
    ):
        """Test getting transaction history after some transactions"""
        # Create some transactions
        await PointsService.award_points_for_task(
            db_session, test_child_user.id, test_task.id, 50
        )
        await PointsService.award_points_for_task(
            db_session, test_child_user.id, test_task.id, 30
        )

        history = await PointsService.get_transaction_history(
            db_session, test_child_user.id
        )

        assert len(history) == 2
        # Most recent first
        assert history[0].points == 30
        assert history[1].points == 50

    async def test_get_transaction_history_with_limit(
        self, db_session, test_child_user, test_task
    ):
        """Test transaction history respects limit parameter"""
        # Create multiple transactions
        for i in range(10):
            await PointsService.award_points_for_task(
                db_session, test_child_user.id, test_task.id, 10
            )

        history = await PointsService.get_transaction_history(
            db_session, test_child_user.id, limit=5
        )

        assert len(history) == 5
