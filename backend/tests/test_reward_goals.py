"""
Tests for RewardGoalService — Task 5 (6 core tests).
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, func
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


# ── Nudge + mark_achieved tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_nudge_fires_notification(db_session, test_family, test_child_user, test_reward):
    # test_child_user.points=100, test_reward.points_cost=100 → affordable
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.check_nudge(
        user_id=test_child_user.id,
        family_id=test_family.id,
        new_balance=100,
        db=db_session,
    )
    from app.models.notification import Notification as Notif
    notif = (
        await db_session.execute(
            select(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar_one_or_none()
    assert notif is not None
    assert notif.link == "/rewards"


@pytest.mark.asyncio
async def test_check_nudge_does_not_refire(db_session, test_family, test_child_user, test_reward):
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 100, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 150, db_session)

    from app.models.notification import Notification as Notif
    count = (
        await db_session.execute(
            select(func.count()).select_from(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_check_nudge_does_not_fire_below_threshold(db_session, test_family, test_child_user, test_reward):
    # test_reward.points_cost=100; new_balance=50 → not affordable
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 50, db_session)

    from app.models.notification import Notification as Notif
    notif = (
        await db_session.execute(
            select(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar_one_or_none()
    assert notif is None


@pytest.mark.asyncio
async def test_check_nudge_refires_after_new_goal(db_session, test_family, test_child_user, test_reward):
    from app.models.reward import Reward, RewardCategory
    reward2 = Reward(
        family_id=test_family.id, title="R2", points_cost=80,
        category=RewardCategory.TOYS, is_active=True,
    )
    db_session.add(reward2)
    await db_session.commit()
    await db_session.refresh(reward2)

    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 100, db_session)
    # Switch goal → nudge_sent_at reset on new row
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, reward2.id, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 100, db_session)

    from app.models.notification import Notification as Notif
    count = (
        await db_session.execute(
            select(func.count()).select_from(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar()
    assert count == 2


@pytest.mark.asyncio
async def test_mark_achieved_sets_timestamp(db_session, test_family, test_child_user, test_reward):
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.mark_achieved(test_child_user.id, test_reward.id, db_session)
    await db_session.commit()

    goal = (
        await db_session.execute(
            select(UserRewardGoal).where(
                UserRewardGoal.user_id == test_child_user.id,
                UserRewardGoal.reward_id == test_reward.id,
            )
        )
    ).scalar_one_or_none()
    assert goal is not None
    assert goal.achieved_at is not None


@pytest.mark.asyncio
async def test_mark_achieved_noop_when_no_goal(db_session, test_family, test_child_user, test_reward):
    # Must not raise
    await RewardGoalService.mark_achieved(test_child_user.id, test_reward.id, db_session)


@pytest.mark.asyncio
async def test_new_goal_settable_after_achieved(db_session, test_family, test_child_user, test_reward):
    from app.models.reward import Reward, RewardCategory
    reward2 = Reward(
        family_id=test_family.id, title="R3", points_cost=50,
        category=RewardCategory.TOYS, is_active=True,
    )
    db_session.add(reward2)
    await db_session.commit()
    await db_session.refresh(reward2)

    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.mark_achieved(test_child_user.id, test_reward.id, db_session)
    await db_session.commit()
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, reward2.id, db_session)

    progress = await RewardGoalService.get_active_goal(test_child_user.id, test_family.id, db_session)
    assert progress is not None
    assert progress.reward_id == reward2.id


# ── HTTP route tests ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def child_headers(client: AsyncClient, test_child_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def parent_headers(client: AsyncClient, test_parent_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_get_goal_returns_null_when_none(client, child_headers, test_child_user, test_family):
    res = await client.get("/api/rewards/goal", headers=child_headers)
    assert res.status_code == 200
    assert res.json() is None


@pytest.mark.asyncio
async def test_put_goal_sets_and_returns_progress(client, child_headers, test_child_user, test_family, test_reward):
    res = await client.put(
        "/api/rewards/goal",
        json={"reward_id": str(test_reward.id)},
        headers=child_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["reward_id"] == str(test_reward.id)
    assert "progress_pct" in data
    assert "pts_to_go" in data
    assert "affordable" in data


@pytest.mark.asyncio
async def test_delete_goal_clears(client, child_headers, test_child_user, test_family, test_reward, db_session):
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    res = await client.delete("/api/rewards/goal", headers=child_headers)
    assert res.status_code == 204
    check = await client.get("/api/rewards/goal", headers=child_headers)
    assert check.json() is None


@pytest.mark.asyncio
async def test_parent_put_goal_forbidden(client, parent_headers, test_family, test_reward):
    res = await client.put(
        "/api/rewards/goal",
        json={"reward_id": str(test_reward.id)},
        headers=parent_headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_parent_get_goal_returns_null(client, parent_headers, test_family):
    res = await client.get("/api/rewards/goal", headers=parent_headers)
    assert res.status_code == 200
    assert res.json() is None


# ── Integration: gig approve triggers nudge ───────────────────────────────────

@pytest.mark.asyncio
async def test_gig_approve_triggers_nudge(db_session, test_family, test_child_user, test_parent_user, test_reward):
    """Approving a gig that pushes balance to goal threshold fires GOAL_REACHED."""
    from app.models.gig import GigOffering, GigClaim, GigClaimStatus, GigCategory
    from app.services.gig_claim_service import GigClaimService

    test_child_user.points = 50  # 50 pts below test_reward.points_cost=100
    await db_session.commit()

    offering = GigOffering(
        family_id=test_family.id,
        created_by=test_parent_user.id,
        title="Wash car",
        points=50,
        difficulty=1,
        category=GigCategory.CHORES,
    )
    db_session.add(offering)
    await db_session.commit()
    await db_session.refresh(offering)

    claim = GigClaim(
        gig_id=offering.id,
        family_id=test_family.id,
        claimed_by=test_child_user.id,
        status=GigClaimStatus.COMPLETED,
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await GigClaimService.approve(
        db=db_session,
        claim_id=claim.id,
        family_id=test_family.id,
        approver_id=test_parent_user.id,
        approved=True,
        notes=None,
    )

    from app.models.notification import Notification as Notif
    notif = (
        await db_session.execute(
            select(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar_one_or_none()
    assert notif is not None
