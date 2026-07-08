"""
RewardGoalService — manage per-user reward saving goals.

Supports set/get/clear goal, nudge notifications when balance crosses the
goal threshold, and marking a goal achieved when the reward is redeemed.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.reward import Reward
from app.models.reward_goal import UserRewardGoal
from app.models.user import User
from app.schemas.reward_goal import GoalProgress

log = logging.getLogger(__name__)


class RewardGoalService:

    @staticmethod
    async def set_goal(
        user_id: UUID,
        family_id: UUID,
        reward_id: UUID,
        db: AsyncSession,
    ) -> UserRewardGoal:
        """Set (or replace) the active saving goal for a user.

        Validates the reward exists and is active within the family.
        Deletes any existing active goal (achieved_at IS NULL) then inserts
        the new one. Using delete+insert rather than ON CONFLICT because
        SQLAlchemy async lacks a clean partial-index conflict target.
        """
        reward = await db.scalar(
            select(Reward).where(
                Reward.id == reward_id,
                Reward.family_id == family_id,
                Reward.is_active.is_(True),
            )
        )
        if not reward:
            raise NotFoundException("Reward not found or not active")

        await db.execute(
            delete(UserRewardGoal).where(
                UserRewardGoal.user_id == user_id,
                UserRewardGoal.family_id == family_id,
                UserRewardGoal.achieved_at.is_(None),
            )
        )
        goal = UserRewardGoal(user_id=user_id, family_id=family_id, reward_id=reward_id)
        db.add(goal)
        await db.commit()
        await db.refresh(goal)
        return goal

    @staticmethod
    async def get_active_goal(
        user_id: UUID,
        family_id: UUID,
        db: AsyncSession,
    ) -> Optional[GoalProgress]:
        """Return progress toward the active goal, or None if no goal is set."""
        row = (
            await db.execute(
                select(UserRewardGoal, Reward)
                .join(Reward, UserRewardGoal.reward_id == Reward.id)
                .where(
                    UserRewardGoal.user_id == user_id,
                    UserRewardGoal.family_id == family_id,
                    UserRewardGoal.achieved_at.is_(None),
                )
            )
        ).first()
        if not row:
            return None
        goal, reward = row
        user = await db.get(User, user_id)
        balance = user.points if user else 0
        pts_to_go = max(0, reward.points_cost - balance)
        progress_pct = (
            min(100, round(balance / reward.points_cost * 100))
            if reward.points_cost > 0 else 100
        )
        return GoalProgress(
            reward_id=reward.id,
            reward_title=reward.title,
            reward_icon=reward.icon,
            points_cost=reward.points_cost,
            balance=balance,
            progress_pct=progress_pct,
            pts_to_go=pts_to_go,
            affordable=balance >= reward.points_cost,
            set_at=goal.set_at,
        )

    @staticmethod
    async def clear_goal(user_id: UUID, family_id: UUID, db: AsyncSession) -> None:
        """Remove the active goal (no-op if none exists)."""
        await db.execute(
            delete(UserRewardGoal).where(
                UserRewardGoal.user_id == user_id,
                UserRewardGoal.family_id == family_id,
                UserRewardGoal.achieved_at.is_(None),
            )
        )
        await db.commit()

    @staticmethod
    async def check_nudge(
        user_id: UUID,
        family_id: UUID,
        new_balance: int,
        db: AsyncSession,
    ) -> None:
        """Fire a GOAL_REACHED notification + push exactly once when the user's
        balance crosses the goal threshold for the first time.

        Idempotent: nudge_sent_at is set after first fire, so subsequent calls
        with the same or higher balance are no-ops.
        """
        row = (
            await db.execute(
                select(UserRewardGoal, Reward)
                .join(Reward, UserRewardGoal.reward_id == Reward.id)
                .where(
                    UserRewardGoal.user_id == user_id,
                    UserRewardGoal.family_id == family_id,
                    UserRewardGoal.achieved_at.is_(None),
                    UserRewardGoal.nudge_sent_at.is_(None),
                )
            )
        ).first()
        if not row:
            return
        goal, reward = row
        if new_balance < reward.points_cost:
            return
        try:
            from app.services.notification_service import NotificationService
            await NotificationService.create_localized(
                db,
                family_id=family_id,
                key="goal_reached_kid",
                user_id=user_id,
                params={"reward": reward.title},
                link="/rewards",
                push=True,
            )
        except Exception:
            log.warning("check_nudge: notification failed", exc_info=True)
            return
        # Parent fan-out — oversight signal. Failure must never block the kid
        # nudge nor nudge_sent_at (separate guard).
        try:
            from app.models.user import UserRole

            kid = await db.get(User, user_id)
            kid_name = kid.name if kid else "Kid"
            parents = (
                await db.scalars(
                    select(User).where(
                        User.family_id == family_id,
                        User.role == UserRole.PARENT,
                        User.is_active.is_(True),
                    )
                )
            ).all()
            for parent in parents:
                await NotificationService.create_localized(
                    db,
                    family_id=family_id,
                    key="goal_reached_parent",
                    user_id=parent.id,
                    params={
                        "kid": kid_name,
                        "reward": reward.title,
                        "pts": reward.points_cost,
                    },
                    link="/parent",
                    push=True,
                    lang=getattr(parent, "preferred_lang", None) or "es",
                )
        except Exception:
            log.warning("check_nudge: parent fan-out failed", exc_info=True)
        goal.nudge_sent_at = datetime.now(timezone.utc)
        await db.commit()

    @staticmethod
    async def get_family_goals(
        family_id: UUID,
        db: AsyncSession,
    ) -> dict[UUID, GoalProgress]:
        """All active goals in the family, keyed by user_id. One JOIN query —
        balance comes from the joined User row (no per-row lookups)."""
        rows = (
            await db.execute(
                select(UserRewardGoal, Reward, User)
                .join(Reward, UserRewardGoal.reward_id == Reward.id)
                .join(User, UserRewardGoal.user_id == User.id)
                .where(
                    UserRewardGoal.family_id == family_id,
                    UserRewardGoal.achieved_at.is_(None),
                )
            )
        ).all()
        out: dict[UUID, GoalProgress] = {}
        for goal, reward, user in rows:
            balance = int(user.points or 0)
            pts_to_go = max(0, reward.points_cost - balance)
            progress_pct = (
                min(100, round(balance / reward.points_cost * 100))
                if reward.points_cost > 0
                else 100
            )
            out[goal.user_id] = GoalProgress(
                reward_id=reward.id,
                reward_title=reward.title,
                reward_icon=reward.icon,
                points_cost=reward.points_cost,
                balance=balance,
                progress_pct=progress_pct,
                pts_to_go=pts_to_go,
                affordable=balance >= reward.points_cost,
                set_at=goal.set_at,
            )
        return out

    @staticmethod
    async def mark_achieved(
        user_id: UUID,
        reward_id: UUID,
        db: AsyncSession,
    ) -> None:
        """Set achieved_at on the active goal matching this reward.

        Called by RewardService.redeem_reward — the caller is responsible for
        committing the outer transaction.
        """
        goal = (
            await db.execute(
                select(UserRewardGoal).where(
                    UserRewardGoal.user_id == user_id,
                    UserRewardGoal.reward_id == reward_id,
                    UserRewardGoal.achieved_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not goal:
            return
        goal.achieved_at = datetime.now(timezone.utc)
