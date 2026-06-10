"""OnboardingService — unit tests."""
import pytest

from app.services.onboarding_service import OnboardingService


@pytest.mark.asyncio
async def test_get_state_all_false(db_session, test_family):
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.child_invited is False
    assert state.task_created is False
    assert state.reward_created is False
    assert state.points_awarded is False
    assert state.dismissed is False
    assert state.all_done is False


@pytest.mark.asyncio
async def test_advance_sets_flag(db_session, test_family):
    await OnboardingService.advance(test_family.id, "task_created", db_session)
    await db_session.commit()
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.task_created is True


@pytest.mark.asyncio
async def test_advance_idempotent(db_session, test_family):
    await OnboardingService.advance(test_family.id, "reward_created", db_session)
    await db_session.commit()
    await OnboardingService.advance(test_family.id, "reward_created", db_session)
    await db_session.commit()
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.reward_created is True  # no error, stays True


@pytest.mark.asyncio
async def test_all_done_computed(db_session, test_family):
    for step in ["child_invited", "task_created", "reward_created", "points_awarded"]:
        await OnboardingService.advance(test_family.id, step, db_session)
    await db_session.commit()
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.all_done is True


@pytest.mark.asyncio
async def test_dismiss(db_session, test_family):
    await OnboardingService.dismiss(test_family.id, db_session)
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.dismissed is True


# ── Route tests ──────────────────────────────────────────────────────────────

import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def parent_client(client, test_parent_user):
    """Authenticated client for test_parent_user (Bearer token injected)."""
    r = await client.post("/api/auth/login", json={
        "email": "parent@test.com", "password": "password123",
    })
    assert r.status_code == 200
    token = r.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest.mark.asyncio
async def test_get_onboarding_state(parent_client, test_family):
    r = await parent_client.get("/api/families/onboarding")
    assert r.status_code == 200
    data = r.json()
    assert "task_created" in data
    assert data["all_done"] is False


@pytest.mark.asyncio
async def test_dismiss_onboarding(parent_client, test_family):
    r = await parent_client.post("/api/families/onboarding/dismiss")
    assert r.status_code == 204
    r2 = await parent_client.get("/api/families/onboarding")
    assert r2.json()["dismissed"] is True


@pytest.mark.asyncio
async def test_onboarding_requires_parent(client, test_child_user):
    r = await client.post("/api/auth/login", json={
        "email": "child@test.com", "password": "password123",
    })
    assert r.status_code == 200
    token = r.json()["access_token"]
    r2 = await client.get(
        "/api/families/onboarding",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 403


# ── Hook integration tests ───────────────────────────────────────────────────
from app.services.task_template_service import TaskTemplateService
from app.schemas.task_template import TaskTemplateCreate


@pytest.mark.asyncio
async def test_advance_task_created_via_hook(
    db_session, test_family, test_parent_user,
):
    data = TaskTemplateCreate(
        title="Clean room",
        points=0,
        effort_level=1,
        interval_days=7,
        assignment_type="auto",
        is_bonus=False,
    )
    await TaskTemplateService.create_template(
        db_session, data, test_family.id, test_parent_user.id,
    )
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.task_created is True


@pytest.mark.asyncio
async def test_advance_reward_created_via_hook(
    db_session, test_family, test_parent_user,
):
    from app.services.reward_service import RewardService
    from app.schemas.reward import RewardCreate
    from app.models.reward import RewardCategory

    data = RewardCreate(
        title="Extra screen time",
        points_cost=50,
        category=RewardCategory.SCREEN_TIME,
        icon="🎮",
    )
    await RewardService.create_reward(db_session, data, test_family.id)
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.reward_created is True
