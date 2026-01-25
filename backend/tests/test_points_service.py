"""
Tests for points_service helper functions

Tests the point transaction helpers added in Phase 4:
- award_points_for_task()
- deduct_points_for_reward()
"""

import pytest
from uuid import uuid4

from app.services.points_service import PointsService
from app.core.exceptions import NotFoundException, ValidationException


@pytest.mark.asyncio
class TestAwardPointsForTask:
    """Test award_points_for_task helper function"""

    async def test_award_points_creates_transaction(
        self, db_session, test_child_user, test_task
    ):
        """Test that awarding points creates a transaction"""
        initial_points = test_child_user.points
        points_to_award = 50

        transaction = await PointsService.award_points_for_task(
            db=db_session,
            user_id=test_child_user.id,
            task_id=test_task.id,
            points=points_to_award,
        )

        # Verify transaction was created
        assert transaction is not None
        assert transaction.user_id == test_child_user.id
        assert transaction.task_id == test_task.id
        assert transaction.points == points_to_award
        assert transaction.balance_before == initial_points
        assert transaction.balance_after == initial_points + points_to_award

    async def test_award_points_updates_user_balance(
        self, db_session, test_child_user, test_task
    ):
        """Test that awarding points updates the user's balance"""
        initial_points = test_child_user.points
        points_to_award = 75

        await PointsService.award_points_for_task(
            db=db_session,
            user_id=test_child_user.id,
            task_id=test_task.id,
            points=points_to_award,
        )

        # Refresh user to get updated balance
        await db_session.refresh(test_child_user)

        assert test_child_user.points == initial_points + points_to_award

    async def test_award_points_with_zero_points(
        self, db_session, test_child_user, test_task
    ):
        """Test awarding zero points (edge case)"""
        initial_points = test_child_user.points

        transaction = await PointsService.award_points_for_task(
            db=db_session,
            user_id=test_child_user.id,
            task_id=test_task.id,
            points=0,
        )

        assert transaction.points == 0
        await db_session.refresh(test_child_user)
        assert test_child_user.points == initial_points

    async def test_award_points_with_large_amount(
        self, db_session, test_child_user, test_task
    ):
        """Test awarding a large amount of points"""
        initial_points = test_child_user.points
        points_to_award = 10000

        transaction = await PointsService.award_points_for_task(
            db=db_session,
            user_id=test_child_user.id,
            task_id=test_task.id,
            points=points_to_award,
        )

        await db_session.refresh(test_child_user)
        assert test_child_user.points == initial_points + points_to_award
        assert transaction.balance_after == initial_points + points_to_award

    async def test_award_points_for_nonexistent_user(self, db_session, test_task):
        """Test awarding points to a user that doesn't exist"""
        non_existent_user_id = uuid4()

        with pytest.raises(NotFoundException):
            await PointsService.award_points_for_task(
                db=db_session,
                user_id=non_existent_user_id,
                task_id=test_task.id,
                points=50,
            )

    async def test_award_points_multiple_times(
        self, db_session, test_child_user, test_task
    ):
        """Test awarding points multiple times accumulates correctly"""
        initial_points = test_child_user.points

        # Award points first time
        await PointsService.award_points_for_task(
            db=db_session,
            user_id=test_child_user.id,
            task_id=test_task.id,
            points=30,
        )

        await db_session.refresh(test_child_user)
        after_first = test_child_user.points

        # Award points second time
        await PointsService.award_points_for_task(
            db=db_session,
            user_id=test_child_user.id,
            task_id=test_task.id,
            points=20,
        )

        await db_session.refresh(test_child_user)

        assert test_child_user.points == initial_points + 30 + 20
        assert test_child_user.points == after_first + 20


@pytest.mark.asyncio
class TestDeductPointsForReward:
    """Test deduct_points_for_reward helper function"""

    async def test_deduct_points_creates_transaction(
        self, db_session, test_child_user, test_reward
    ):
        """Test that deducting points creates a transaction"""
        # Give user enough points first
        test_child_user.points = 100
        await db_session.commit()

        initial_points = test_child_user.points
        points_to_deduct = 50

        transaction = await PointsService.deduct_points_for_reward(
            db=db_session,
            user_id=test_child_user.id,
            reward_id=test_reward.id,
            points_cost=points_to_deduct,
        )

        # Verify transaction was created
        assert transaction is not None
        assert transaction.user_id == test_child_user.id
        assert transaction.reward_id == test_reward.id
        assert transaction.points == -points_to_deduct
        assert transaction.balance_before == initial_points
        assert transaction.balance_after == initial_points - points_to_deduct

    async def test_deduct_points_updates_user_balance(
        self, db_session, test_child_user, test_reward
    ):
        """Test that deducting points updates the user's balance"""
        # Give user enough points first
        test_child_user.points = 100
        await db_session.commit()

        initial_points = test_child_user.points
        points_to_deduct = 75

        await PointsService.deduct_points_for_reward(
            db=db_session,
            user_id=test_child_user.id,
            reward_id=test_reward.id,
            points_cost=points_to_deduct,
        )

        # Refresh user to get updated balance
        await db_session.refresh(test_child_user)

        assert test_child_user.points == initial_points - points_to_deduct

    async def test_deduct_points_insufficient_balance(
        self, db_session, test_child_user, test_reward
    ):
        """Test that deducting points fails with insufficient balance"""
        # User has 0 points by default
        test_child_user.points = 10
        await db_session.commit()

        with pytest.raises(ValidationException) as exc_info:
            await PointsService.deduct_points_for_reward(
                db=db_session,
                user_id=test_child_user.id,
                reward_id=test_reward.id,
                points_cost=50,
            )

        assert "insufficient points" in str(exc_info.value).lower()

        # Verify balance wasn't changed
        await db_session.refresh(test_child_user)
        assert test_child_user.points == 10

    async def test_deduct_points_exact_balance(
        self, db_session, test_child_user, test_reward
    ):
        """Test deducting points when user has exact amount"""
        points_amount = 50
        test_child_user.points = points_amount
        await db_session.commit()

        transaction = await PointsService.deduct_points_for_reward(
            db=db_session,
            user_id=test_child_user.id,
            reward_id=test_reward.id,
            points_cost=points_amount,
        )

        await db_session.refresh(test_child_user)
        assert test_child_user.points == 0
        assert transaction.balance_after == 0

    async def test_deduct_points_for_nonexistent_user(self, db_session, test_reward):
        """Test deducting points from a user that doesn't exist"""
        non_existent_user_id = uuid4()

        with pytest.raises(NotFoundException):
            await PointsService.deduct_points_for_reward(
                db=db_session,
                user_id=non_existent_user_id,
                reward_id=test_reward.id,
                points_cost=50,
            )

    async def test_deduct_zero_points(self, db_session, test_child_user, test_reward):
        """Test deducting zero points (edge case)"""
        test_child_user.points = 100
        await db_session.commit()

        initial_points = test_child_user.points

        transaction = await PointsService.deduct_points_for_reward(
            db=db_session,
            user_id=test_child_user.id,
            reward_id=test_reward.id,
            points_cost=0,
        )

        await db_session.refresh(test_child_user)
        assert test_child_user.points == initial_points
        assert transaction.points == 0

    async def test_award_then_deduct_points(
        self, db_session, test_child_user, test_task, test_reward
    ):
        """Test award and deduct flow (realistic scenario)"""
        initial_points = test_child_user.points

        # Award points from task
        await PointsService.award_points_for_task(
            db=db_session,
            user_id=test_child_user.id,
            task_id=test_task.id,
            points=100,
        )

        await db_session.refresh(test_child_user)
        assert test_child_user.points == initial_points + 100

        # Deduct points for reward
        await PointsService.deduct_points_for_reward(
            db=db_session,
            user_id=test_child_user.id,
            reward_id=test_reward.id,
            points_cost=60,
        )

        await db_session.refresh(test_child_user)
        assert test_child_user.points == initial_points + 100 - 60
