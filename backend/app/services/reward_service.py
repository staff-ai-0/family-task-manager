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
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.task_template import TaskTemplate
from app.schemas.reward import RewardCreate, RewardUpdate
from app.core.exceptions import (
    NotFoundException,
    ForbiddenException,
    ValidationException,
)
from app.services.base_service import BaseFamilyService, verify_user_in_family
from app.services.points_service import PointsService


class RewardService(BaseFamilyService[Reward]):
    """Service for reward-related operations"""

    model = Reward

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
        try:
            import logging
            from app.services.onboarding_service import OnboardingService
            await OnboardingService.advance(family_id, "reward_created", db)
            await db.commit()
        except Exception:
            logging.getLogger(__name__).warning(
                "onboarding advance reward_created failed", exc_info=True
            )
        return reward

    @staticmethod
    async def get_reward(db: AsyncSession, reward_id: UUID, family_id: UUID) -> Reward:
        """Get a reward by ID"""
        return await RewardService.get_by_id(db, reward_id, family_id)

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
        update_fields = reward_data.model_dump(exclude_unset=True)
        return await RewardService.update_by_id(db, reward_id, family_id, update_fields)

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

        # Verify user belongs to family
        await verify_user_in_family(db, user_id, family_id)

        # Check for active consequences that block reward redemption
        active_restrictions = (
            await db.execute(
                select(Consequence).where(
                    and_(
                        Consequence.applied_to_user == user_id,
                        Consequence.active == True,
                        Consequence.restriction_type.in_(["rewards", "REWARDS"]),
                    )
                )
            )
        ).scalar_one_or_none()

        if active_restrictions:
            raise ForbiddenException(
                "You have an active consequence that prevents reward redemption"
            )

        # Chore locking (W1.3): any open assignment from a template with
        # blocks_rewards=True gates redemption. PENDING and OVERDUE both count.
        locking_q = (
            select(TaskTemplate.title)
            .join(TaskAssignment, TaskAssignment.template_id == TaskTemplate.id)
            .where(
                and_(
                    TaskAssignment.assigned_to == user_id,
                    TaskAssignment.family_id == family_id,
                    TaskAssignment.status.in_(
                        [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]
                    ),
                    TaskTemplate.blocks_rewards.is_(True),
                )
            )
            .limit(5)
        )
        locking_titles = [row[0] for row in (await db.execute(locking_q)).all()]
        if locking_titles:
            joined = ", ".join(locking_titles)
            raise ForbiddenException(
                f"Finish your locked chores before redeeming rewards: {joined}"
            )

        # Deduct points using PointsService
        transaction = await PointsService.deduct_points_for_reward(
            db=db,
            user_id=user_id,
            reward_id=reward.id,
            points_cost=reward.points_cost,
        )

        try:
            from app.services.reward_goal_service import RewardGoalService
            await RewardGoalService.mark_achieved(
                user_id=user_id, reward_id=reward.id, db=db
            )
            await db.commit()
        except Exception:
            import logging
            logging.getLogger(__name__).warning("mark_achieved failed", exc_info=True)

        try:
            from app.services.push_service import PushService as _PushService
            await _PushService.send_to_user(db, user_id, {
                "title": "¡Recompensa canjeada! 🎁",
                "body": reward.title,
                "url": "/rewards",
                "tag": "reward-redeemed",
            })
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "push reward-redeemed failed", exc_info=True
            )

        # Notify parents — before this, a kid could redeem "30 min screen time"
        # and no parent ever learned of it (the redeemer got the only push).
        try:
            from app.services.notification_service import NotificationService
            from app.models.notification import NotificationType as NT
            from app.models.user import User, UserRole

            redeemer = await db.get(User, user_id)
            redeemer_name = redeemer.name if redeemer else "A kid"
            parents = (await db.scalars(
                select(User).where(
                    and_(
                        User.family_id == family_id,
                        User.role == UserRole.PARENT,
                        User.is_active.is_(True),
                        User.id != user_id,  # don't notify the redeemer about their own action
                    )
                )
            )).all()
            for parent in parents:
                p_es = getattr(parent, "preferred_lang", "en") == "es"
                await NotificationService.create(
                    db,
                    family_id=family_id,
                    user_id=parent.id,
                    type=NT.REWARD_REDEEMED,
                    title="🎁 " + ("Recompensa canjeada" if p_es else "Reward redeemed"),
                    body=(
                        f"{redeemer_name} canjeó \"{reward.title}\" por {reward.points_cost} puntos."
                        if p_es else
                        f"{redeemer_name} redeemed \"{reward.title}\" for {reward.points_cost} points."
                    ),
                    link="/parent/rewards",
                )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "notify parents of reward redemption failed", exc_info=True
            )

        return transaction

    @staticmethod
    async def delete_reward(db: AsyncSession, reward_id: UUID, family_id: UUID) -> None:
        """Delete a reward"""
        await RewardService.delete_by_id(db, reward_id, family_id)

    @staticmethod
    async def get_user_redemption_count(
        db: AsyncSession, user_id: UUID, reward_id: UUID
    ) -> int:
        """Get number of times user has redeemed a specific reward"""
        query = (
            select(func.count())
            .select_from(PointTransaction)
            .where(
                and_(
                    PointTransaction.user_id == user_id,
                    PointTransaction.reward_id == reward_id,
                )
            )
        )
        result = await db.execute(query)
        return result.scalar() or 0
