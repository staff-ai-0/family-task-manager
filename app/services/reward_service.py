"""
Reward Service

Business logic for reward management and redemption.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Optional
from datetime import datetime
from uuid import UUID

from app.models import Reward, User, PointTransaction, Consequence
from app.models.reward import RewardCategory
from app.schemas.reward import RewardCreate, RewardUpdate
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)


class RewardService:
    """Service for reward-related operations"""

    @staticmethod
    async def create_reward(
        db: AsyncSession,
        reward_data: RewardCreate,
        family_id: UUID,
    ) -> Reward:
        """Create a new reward"""
        reward = Reward(
            title=reward_data.title,
            description=reward_data.description,
            points_cost=reward_data.points_cost,
            category=reward_data.category,
            icon=reward_data.icon,
            requires_parent_approval=reward_data.requires_parent_approval,
            family_id=family_id,
            is_active=True,
        )
        
        db.add(reward)
        await db.commit()
        await db.refresh(reward)
        return reward

    @staticmethod
    async def get_reward(db: AsyncSession, reward_id: UUID, family_id: UUID) -> Reward:
        """Get a reward by ID"""
        query = select(Reward).where(
            and_(Reward.id == reward_id, Reward.family_id == family_id)
        )
        reward = (await db.execute(query)).scalar_one_or_none()
        if not reward:
            raise NotFoundException("Reward not found")
        return reward

    @staticmethod
    async def list_rewards(
        db: AsyncSession,
        family_id: UUID,
        category: Optional[RewardCategory] = None,
        is_active: Optional[bool] = True,
    ) -> List[Reward]:
        """List rewards with optional filters"""
        query = select(Reward).where(Reward.family_id == family_id)
        
        if category:
            query = query.where(Reward.category == category)
        if is_active is not None:
            query = query.where(Reward.is_active == is_active)
        
        query = query.order_by(Reward.points_cost.asc(), Reward.title.asc())
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def update_reward(
        db: AsyncSession,
        reward_id: UUID,
        reward_data: RewardUpdate,
        family_id: UUID,
    ) -> Reward:
        """Update reward details"""
        reward = await RewardService.get_reward(db, reward_id, family_id)
        
        # Update fields if provided
        update_fields = reward_data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(reward, field, value)
        
        reward.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(reward)
        return reward

    @staticmethod
    async def redeem_reward(
        db: AsyncSession,
        reward_id: UUID,
        user_id: UUID,
        family_id: UUID,
    ) -> PointTransaction:
        """Redeem a reward with user's points"""
        # Get reward
        reward = await RewardService.get_reward(db, reward_id, family_id)
        
        # Check if reward is redeemable
        if not reward.is_redeemable:
            raise ValidationException("This reward is currently not available")
        
        # Get user
        user = (await db.execute(
            select(User).where(and_(User.id == user_id, User.family_id == family_id))
        )).scalar_one_or_none()
        if not user:
            raise NotFoundException("User not found")
        
        # Check if user has enough points
        if user.points < reward.points_cost:
            raise ValidationException(
                f"Insufficient points. Need {reward.points_cost}, have {user.points}"
            )
        
        # Check for active consequences that block reward redemption
        active_restrictions = (await db.execute(
            select(Consequence).where(
                and_(
                    Consequence.applied_to_user == user_id,
                    Consequence.active == True,
                    Consequence.restriction_type.in_(['rewards', 'REWARDS']),
                )
            )
        )).scalar_one_or_none()
        
        if active_restrictions:
            raise ForbiddenException(
                "You have an active consequence that prevents reward redemption"
            )
        
        # Create transaction and deduct points
        transaction = PointTransaction.create_reward_redemption(
            user_id=user_id,
            reward_id=reward.id,
            points_cost=reward.points_cost,
            balance_before=user.points,
        )
        user.points -= reward.points_cost
        
        db.add(transaction)
        await db.commit()
        await db.refresh(transaction)
        
        return transaction

    @staticmethod
    async def delete_reward(db: AsyncSession, reward_id: UUID, family_id: UUID) -> None:
        """Delete a reward"""
        reward = await RewardService.get_reward(db, reward_id, family_id)
        await db.delete(reward)
        await db.commit()

    @staticmethod
    async def get_user_redemption_count(
        db: AsyncSession, user_id: UUID, reward_id: UUID
    ) -> int:
        """Get number of times user has redeemed a specific reward"""
        query = select(func.count()).select_from(PointTransaction).where(
            and_(
                PointTransaction.user_id == user_id,
                PointTransaction.reward_id == reward_id,
            )
        )
        result = await db.execute(query)
        return result.scalar() or 0
