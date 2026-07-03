"""Parent-approval reward redemption queue.

High-value rewards (requires_parent_approval=True) must NOT deduct points on
redeem — they queue as PENDING until a parent approves (deduct then) or rejects
(no deduction). Rewards without the flag deduct immediately as before.
"""
import pytest
from sqlalchemy import select

from app.models.reward import Reward, RewardCategory, RewardRedemption, RedemptionStatus
from app.models.notification import Notification, NotificationType
from app.services.reward_service import RewardService
from app.core.exceptions import ValidationException
from app.core.security import create_access_token


async def _reward(db, family, *, cost=50, approval=False):
    r = Reward(
        family_id=family.id, title="Movie Night", description="",
        points_cost=cost, category=RewardCategory.ACTIVITIES,
        is_active=True, requires_parent_approval=approval,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r


def _tok(user):
    return create_access_token(data={
        "sub": str(user.id), "family_id": str(user.family_id), "role": user.role.value,
    })


@pytest.mark.asyncio
async def test_approval_reward_queues_without_deducting(
    db_session, test_family, test_child_user, test_parent_user
):
    test_child_user.points = 200
    await db_session.commit()
    reward = await _reward(db_session, test_family, cost=80, approval=True)

    result = await RewardService.redeem_reward(
        db_session, reward_id=reward.id, user_id=test_child_user.id, family_id=test_family.id,
    )
    assert result["status"] == "pending"
    assert result["points_spent"] == 0

    await db_session.refresh(test_child_user)
    assert test_child_user.points == 200  # NOT deducted yet

    pending = (await db_session.execute(
        select(RewardRedemption).where(RewardRedemption.user_id == test_child_user.id)
    )).scalars().all()
    assert len(pending) == 1
    assert pending[0].status == RedemptionStatus.PENDING.value
    assert pending[0].points_cost == 80

    # Parent notified.
    notifs = (await db_session.execute(
        select(Notification).where(Notification.user_id == test_parent_user.id)
    )).scalars().all()
    assert any(n.type == NotificationType.REWARD_REDEEMED for n in notifs)


@pytest.mark.asyncio
async def test_non_approval_reward_deducts_immediately(
    db_session, test_family, test_child_user
):
    test_child_user.points = 200
    await db_session.commit()
    reward = await _reward(db_session, test_family, cost=50, approval=False)

    result = await RewardService.redeem_reward(
        db_session, reward_id=reward.id, user_id=test_child_user.id, family_id=test_family.id,
    )
    assert result["status"] == "completed"
    assert result["points_spent"] == 50
    await db_session.refresh(test_child_user)
    assert test_child_user.points == 150


@pytest.mark.asyncio
async def test_cannot_queue_when_unaffordable(db_session, test_family, test_child_user):
    test_child_user.points = 10
    await db_session.commit()
    reward = await _reward(db_session, test_family, cost=80, approval=True)
    with pytest.raises(ValidationException):
        await RewardService.redeem_reward(
            db_session, reward_id=reward.id, user_id=test_child_user.id, family_id=test_family.id,
        )


@pytest.mark.asyncio
async def test_approve_deducts_and_notifies_kid(
    db_session, test_family, test_child_user, test_parent_user
):
    test_child_user.points = 200
    await db_session.commit()
    reward = await _reward(db_session, test_family, cost=80, approval=True)
    await RewardService.redeem_reward(
        db_session, reward_id=reward.id, user_id=test_child_user.id, family_id=test_family.id,
    )
    redemption = (await db_session.execute(select(RewardRedemption))).scalars().first()

    decided = await RewardService.decide_redemption(
        db_session, redemption_id=redemption.id, family_id=test_family.id,
        parent_id=test_parent_user.id, approve=True,
    )
    assert decided.status == RedemptionStatus.APPROVED.value
    assert decided.transaction_id is not None
    await db_session.refresh(test_child_user)
    assert test_child_user.points == 120  # 200 - 80

    kid_notifs = (await db_session.execute(
        select(Notification).where(Notification.user_id == test_child_user.id)
    )).scalars().all()
    assert any(n.type == NotificationType.REWARD_REDEEMED for n in kid_notifs)


@pytest.mark.asyncio
async def test_reject_does_not_deduct(
    db_session, test_family, test_child_user, test_parent_user
):
    test_child_user.points = 200
    await db_session.commit()
    reward = await _reward(db_session, test_family, cost=80, approval=True)
    await RewardService.redeem_reward(
        db_session, reward_id=reward.id, user_id=test_child_user.id, family_id=test_family.id,
    )
    redemption = (await db_session.execute(select(RewardRedemption))).scalars().first()

    decided = await RewardService.decide_redemption(
        db_session, redemption_id=redemption.id, family_id=test_family.id,
        parent_id=test_parent_user.id, approve=False, notes="Not this week",
    )
    assert decided.status == RedemptionStatus.REJECTED.value
    await db_session.refresh(test_child_user)
    assert test_child_user.points == 200  # untouched


@pytest.mark.asyncio
async def test_cannot_decide_twice(db_session, test_family, test_child_user, test_parent_user):
    test_child_user.points = 200
    await db_session.commit()
    reward = await _reward(db_session, test_family, cost=80, approval=True)
    await RewardService.redeem_reward(
        db_session, reward_id=reward.id, user_id=test_child_user.id, family_id=test_family.id,
    )
    redemption = (await db_session.execute(select(RewardRedemption))).scalars().first()
    await RewardService.decide_redemption(
        db_session, redemption_id=redemption.id, family_id=test_family.id,
        parent_id=test_parent_user.id, approve=True,
    )
    with pytest.raises(ValidationException):
        await RewardService.decide_redemption(
            db_session, redemption_id=redemption.id, family_id=test_family.id,
            parent_id=test_parent_user.id, approve=False,
        )


@pytest.mark.asyncio
async def test_route_kid_cannot_list_or_approve(
    client, db_session, test_family, test_child_user
):
    headers = {"Authorization": f"Bearer {_tok(test_child_user)}"}
    r = await client.get("/api/rewards/redemptions/pending", headers=headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_route_parent_sees_pending(
    client, db_session, test_family, test_child_user, test_parent_user
):
    test_child_user.points = 200
    await db_session.commit()
    reward = await _reward(db_session, test_family, cost=80, approval=True)
    await RewardService.redeem_reward(
        db_session, reward_id=reward.id, user_id=test_child_user.id, family_id=test_family.id,
    )
    headers = {"Authorization": f"Bearer {_tok(test_parent_user)}"}
    r = await client.get("/api/rewards/redemptions/pending", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["reward_title"] == "Movie Night"
    assert body[0]["user_name"] == test_child_user.name
