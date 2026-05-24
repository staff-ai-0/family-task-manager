"""Chore locking: open assignments with blocks_rewards block reward redemption."""

import pytest
from datetime import date, timedelta

from app.models.task_template import TaskTemplate
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.reward import Reward, RewardCategory
from app.services.reward_service import RewardService
from app.core.exceptions import ForbiddenException


async def _seed_reward(db, family, points_cost=5):
    r = Reward(
        title="Ice cream",
        points_cost=points_cost,
        category=RewardCategory.TREATS,
        family_id=family.id,
        is_active=True,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r


async def _seed_open_assignment(
    db,
    family,
    user,
    *,
    blocks_rewards: bool,
    status: AssignmentStatus = AssignmentStatus.PENDING,
):
    tmpl = TaskTemplate(
        title="Dishes",
        points=0,
        effort_level=1,
        interval_days=1,
        is_bonus=False,
        blocks_rewards=blocks_rewards,
        family_id=family.id,
        created_by=user.id,
    )
    db.add(tmpl)
    await db.flush()
    d = date.today()
    a = TaskAssignment(
        template_id=tmpl.id,
        assigned_to=user.id,
        family_id=family.id,
        status=status,
        assigned_date=d,
        week_of=d - timedelta(days=d.weekday()),
    )
    db.add(a)
    await db.commit()
    return tmpl, a


class TestChoreLocking:
    async def test_blocks_redemption_when_pending(
        self, db_session, test_family, test_child_user
    ):
        # Give the child enough points to redeem
        test_child_user.points = 100
        await db_session.commit()

        reward = await _seed_reward(db_session, test_family)
        await _seed_open_assignment(
            db_session, test_family, test_child_user, blocks_rewards=True
        )

        with pytest.raises(ForbiddenException) as exc:
            await RewardService.redeem_reward(
                db_session, reward.id, test_child_user.id, test_family.id
            )
        assert "Dishes" in str(exc.value)

    async def test_blocks_redemption_when_overdue(
        self, db_session, test_family, test_child_user
    ):
        test_child_user.points = 100
        await db_session.commit()
        reward = await _seed_reward(db_session, test_family)
        await _seed_open_assignment(
            db_session,
            test_family,
            test_child_user,
            blocks_rewards=True,
            status=AssignmentStatus.OVERDUE,
        )
        with pytest.raises(ForbiddenException):
            await RewardService.redeem_reward(
                db_session, reward.id, test_child_user.id, test_family.id
            )

    async def test_allows_redemption_when_not_blocking(
        self, db_session, test_family, test_child_user
    ):
        test_child_user.points = 100
        await db_session.commit()
        reward = await _seed_reward(db_session, test_family)
        await _seed_open_assignment(
            db_session, test_family, test_child_user, blocks_rewards=False
        )
        # Should not raise
        tx = await RewardService.redeem_reward(
            db_session, reward.id, test_child_user.id, test_family.id
        )
        assert tx is not None

    async def test_allows_redemption_when_blocking_assignment_completed(
        self, db_session, test_family, test_child_user
    ):
        test_child_user.points = 100
        await db_session.commit()
        reward = await _seed_reward(db_session, test_family)
        _, assignment = await _seed_open_assignment(
            db_session, test_family, test_child_user, blocks_rewards=True
        )
        assignment.status = AssignmentStatus.COMPLETED
        await db_session.commit()
        tx = await RewardService.redeem_reward(
            db_session, reward.id, test_child_user.id, test_family.id
        )
        assert tx is not None
