"""Tests for parent oversight: fixes + command center."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def parent_headers(client: AsyncClient, test_parent_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def child_headers(client: AsyncClient, test_child_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── A1: consequence create payload shape ─────────────────────────────────────

@pytest.mark.asyncio
async def test_consequence_create_new_payload_shape(
    client, parent_headers, test_family, test_child_user
):
    """The exact payload the fixed frontend form sends must succeed."""
    res = await client.post(
        "/api/consequences/",
        json={
            "title": "No tablet",
            "description": "Too much screen time",
            "applied_to_user": str(test_child_user.id),
            "restriction_type": "screen_time",
            "severity": "low",
            "duration_days": 3,
        },
        headers=parent_headers,
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    assert data["applied_to_user"] == str(test_child_user.id)
    assert data["restriction_type"] == "screen_time"
    assert data["end_date"] is not None


# ── A4: expired consequence sweep ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_expired_all_resolves_only_expired(
    db_session: AsyncSession, test_family, test_child_user
):
    from datetime import datetime, timedelta, timezone
    from app.models.consequence import Consequence, ConsequenceSeverity, RestrictionType
    from app.services.consequence_service import ConsequenceService

    now = datetime.now(timezone.utc)
    expired = Consequence(
        title="Expired one",
        severity=ConsequenceSeverity.LOW,
        restriction_type=RestrictionType.SCREEN_TIME,
        duration_days=1,
        applied_to_user=test_child_user.id,
        family_id=test_family.id,
        start_date=now - timedelta(days=3),
        end_date=now - timedelta(days=2),
        active=True,
        resolved=False,
    )
    current = Consequence(
        title="Still active",
        severity=ConsequenceSeverity.LOW,
        restriction_type=RestrictionType.REWARDS,
        duration_days=5,
        applied_to_user=test_child_user.id,
        family_id=test_family.id,
        start_date=now,
        end_date=now + timedelta(days=5),
        active=True,
        resolved=False,
    )
    db_session.add_all([expired, current])
    await db_session.commit()

    n = await ConsequenceService.check_expired_all(db_session)
    assert n == 1

    await db_session.refresh(expired)
    await db_session.refresh(current)
    assert expired.active is False
    assert expired.resolved is True
    assert expired.resolved_at is not None
    assert current.active is True
    assert current.resolved is False


# ── A6: analytics includes gig-board claims ───────────────────────────────────

@pytest.mark.asyncio
async def test_analytics_gigs_completed_includes_gig_board(
    db_session: AsyncSession, test_family, test_parent_user, test_child_user
):
    from datetime import datetime, timezone
    from app.models.gig import GigOffering, GigClaim, GigClaimStatus, GigCategory
    from app.services.analytics_service import AnalyticsService

    offering = GigOffering(
        family_id=test_family.id,
        created_by=test_parent_user.id,
        title="Wash car",
        points=30,
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
        status=GigClaimStatus.APPROVED,
        points_awarded=30,
        approved_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(claim)
    await db_session.commit()

    rows = await AnalyticsService.per_member_completion_rate(
        db_session, test_family.id
    )
    kid_row = next(r for r in rows if r["user_id"] == str(test_child_user.id))
    assert kid_row["gigs_completed"] >= 1


# ── B1: get_family_goals ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_family_goals_returns_active_goals_keyed_by_user(
    db_session: AsyncSession, test_family, test_child_user, test_teen_user, test_reward
):
    from app.services.reward_goal_service import RewardGoalService

    await RewardGoalService.set_goal(
        test_child_user.id, test_family.id, test_reward.id, db_session
    )
    goals = await RewardGoalService.get_family_goals(test_family.id, db_session)

    assert test_child_user.id in goals
    assert test_teen_user.id not in goals
    gp = goals[test_child_user.id]
    assert gp.reward_title == test_reward.title
    assert gp.balance == 100
    assert gp.affordable is True


@pytest.mark.asyncio
async def test_get_family_goals_excludes_achieved(
    db_session: AsyncSession, test_family, test_child_user, test_reward
):
    from app.services.reward_goal_service import RewardGoalService

    await RewardGoalService.set_goal(
        test_child_user.id, test_family.id, test_reward.id, db_session
    )
    await RewardGoalService.mark_achieved(test_child_user.id, test_reward.id, db_session)
    await db_session.commit()

    goals = await RewardGoalService.get_family_goals(test_family.id, db_session)
    assert test_child_user.id not in goals


@pytest.mark.asyncio
async def test_get_family_goals_cross_family_isolated(
    db_session: AsyncSession, test_family, test_child_user, test_reward
):
    from app.models.family import Family
    from app.services.reward_goal_service import RewardGoalService

    other = Family(name="Other Family")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    await RewardGoalService.set_goal(
        test_child_user.id, test_family.id, test_reward.id, db_session
    )
    goals = await RewardGoalService.get_family_goals(other.id, db_session)
    assert goals == {}
