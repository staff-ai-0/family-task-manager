"""
Tests for RewardGoalService — Task 5 (6 core tests).
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reward_goal import UserRewardGoal
from app.services.reward_goal_service import RewardGoalService
from app.core.exceptions import NotFoundException


# ── Core service tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_goal_creates_active_row(db_session, test_family, test_child_user, test_reward):
    await RewardGoalService.set_goal(
        user_id=test_child_user.id,
        family_id=test_family.id,
        reward_id=test_reward.id,
        db=db_session,
    )
    goal = (
        await db_session.execute(
            select(UserRewardGoal).where(
                UserRewardGoal.user_id == test_child_user.id,
                UserRewardGoal.achieved_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    assert goal is not None
    assert goal.reward_id == test_reward.id
    assert goal.nudge_sent_at is None


@pytest.mark.asyncio
async def test_set_goal_replaces_existing(db_session, test_family, test_child_user, test_reward):
    from app.models.reward import Reward, RewardCategory
    reward2 = Reward(
        family_id=test_family.id, title="Second Reward",
        points_cost=200, category=RewardCategory.TOYS, is_active=True,
    )
    db_session.add(reward2)
    await db_session.commit()
    await db_session.refresh(reward2)

    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, reward2.id, db_session)

    active = (
        await db_session.execute(
            select(UserRewardGoal).where(
                UserRewardGoal.user_id == test_child_user.id,
                UserRewardGoal.achieved_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(active) == 1
    assert active[0].reward_id == reward2.id


@pytest.mark.asyncio
async def test_get_active_goal_returns_progress(db_session, test_family, test_child_user, test_reward):
    # test_child_user.points=100, test_reward.points_cost=100
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    progress = await RewardGoalService.get_active_goal(test_child_user.id, test_family.id, db_session)

    assert progress is not None
    assert progress.reward_id == test_reward.id
    assert progress.balance == 100
    assert progress.pts_to_go == 0
    assert progress.progress_pct == 100
    assert progress.affordable is True


@pytest.mark.asyncio
async def test_get_active_goal_returns_none_when_no_goal(db_session, test_family, test_child_user):
    result = await RewardGoalService.get_active_goal(test_child_user.id, test_family.id, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_clear_goal_removes_active_row(db_session, test_family, test_child_user, test_reward):
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.clear_goal(test_child_user.id, test_family.id, db_session)
    result = await RewardGoalService.get_active_goal(test_child_user.id, test_family.id, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_set_goal_rejects_inactive_reward(db_session, test_family, test_child_user):
    from app.models.reward import Reward, RewardCategory
    inactive = Reward(
        family_id=test_family.id, title="Inactive", points_cost=50,
        category=RewardCategory.TOYS, is_active=False,
    )
    db_session.add(inactive)
    await db_session.commit()
    await db_session.refresh(inactive)

    with pytest.raises(NotFoundException):
        await RewardGoalService.set_goal(
            test_child_user.id, test_family.id, inactive.id, db_session
        )
