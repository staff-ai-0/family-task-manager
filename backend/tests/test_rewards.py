"""
Tests for Reward System
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


class TestRewardCreation:
    """Test reward creation"""

    @pytest.mark.asyncio
    async def test_parent_create_reward(self, client: AsyncClient, test_parent_user):
        """Test parent can create a reward"""
        # Login as parent
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Create reward
        response = await client.post(
            "/api/rewards/",
            json={
                "title": "Ice Cream Trip",
                "description": "Trip to get ice cream",
                "points_cost": 150,
                "category": "treats",
                "icon": "🍦",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code != 201:
            print(f"Response: {response.json()}")
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Ice Cream Trip"
        assert data["points_cost"] == 150


class TestRewardRedemption:
    """Test reward redemption flow"""

    @pytest.mark.asyncio
    async def test_redeem_reward_with_sufficient_points(
        self,
        client: AsyncClient,
        test_child_user,
        test_reward,
        db_session: AsyncSession,
    ):
        """Test redeeming a reward with sufficient points"""
        initial_points = test_child_user.points

        # Ensure child has enough points
        assert initial_points >= test_reward.points_cost

        # Login as child
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_child_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Redeem reward
        response = await client.post(
            f"/api/rewards/{test_reward.id}/redeem",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200

        # Check points were deducted
        await db_session.refresh(test_child_user)
        assert test_child_user.points == initial_points - test_reward.points_cost

    @pytest.mark.asyncio
    async def test_cannot_redeem_without_sufficient_points(
        self, client: AsyncClient, test_child_user, db_session: AsyncSession
    ):
        """Test cannot redeem reward without enough points"""
        # Set points to 0
        test_child_user.points = 0
        await db_session.commit()

        # Create expensive reward
        from app.models.reward import Reward, RewardCategory

        reward = Reward(
            family_id=test_child_user.family_id,
            title="Expensive Reward",
            description="Costs a lot",
            points_cost=1000,
            category=RewardCategory.TOYS,
            icon="💎",
            is_active=True,
        )
        db_session.add(reward)
        await db_session.commit()
        await db_session.refresh(reward)

        # Login
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_child_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Try to redeem
        response = await client.post(
            f"/api/rewards/{reward.id}/redeem",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 400


class TestRewardListing:
    """Test reward listing"""

    @pytest.mark.asyncio
    async def test_list_family_rewards(
        self, client: AsyncClient, test_child_user, test_reward
    ):
        """Test user can see family rewards"""
        # Login
        login_response = await client.post(
            "/api/auth/login",
            json={"email": test_child_user.email, "password": "password123"},
        )
        token = login_response.json()["access_token"]

        # Get rewards
        response = await client.get(
            "/api/rewards/", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        rewards = response.json()
        assert len(rewards) >= 1
        assert any(reward["id"] == str(test_reward.id) for reward in rewards)
