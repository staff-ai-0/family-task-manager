"""Age-preset starter packs (P1-W3) — data sanity, service, and route tests."""
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.data.starter_packs import AGE_BANDS, STARTER_PACKS
from app.core.exceptions import ValidationException
from app.models.gig import GigCategory, GigOffering
from app.models.reward import Reward, RewardCategory
from app.models.task_template import TaskTemplate
from app.schemas.onboarding import StarterPackApplyRequest
from app.services.onboarding_service import OnboardingService
from app.services.starter_pack_service import StarterPackService


# ── Static data sanity ───────────────────────────────────────────────────────

def test_all_age_bands_present():
    assert set(STARTER_PACKS.keys()) == set(AGE_BANDS)


def test_pack_sizes_per_band():
    for band, pack in STARTER_PACKS.items():
        assert 8 <= len(pack["chores"]) <= 10, band
        assert 4 <= len(pack["gigs"]) <= 6, band
        assert len(pack["rewards"]) == 6, band


def test_item_ids_globally_unique():
    ids = [
        item["id"]
        for pack in STARTER_PACKS.values()
        for kind in ("chores", "gigs", "rewards")
        for item in pack[kind]
    ]
    assert len(ids) == len(set(ids))


def test_items_are_valid_for_models():
    for pack in STARTER_PACKS.values():
        for chore in pack["chores"]:
            assert chore["title_es"] and chore["title_en"]
            assert chore["points"] > 0
            assert 1 <= chore["interval_days"] <= 7
        for gig in pack["gigs"]:
            GigCategory(gig["category"])  # raises on invalid
            assert gig["points"] > 0
            assert 1 <= gig["difficulty"] <= 3
        for reward in pack["rewards"]:
            RewardCategory(reward["category"])  # raises on invalid
            assert reward["points_cost"] > 0


def test_no_money_rewards_two_currency_guard():
    """Points must never convert to cash outside the /gigs board."""
    for pack in STARTER_PACKS.values():
        for reward in pack["rewards"]:
            assert reward["category"] != "money"


def test_list_packs_shape():
    packs = StarterPackService.list_packs().packs
    assert [p.age_band for p in packs] == list(STARTER_PACKS.keys())
    assert all(p.label_es and p.label_en for p in packs)


# ── Service: apply ───────────────────────────────────────────────────────────

async def _count(db, model, family_id):
    return (await db.execute(
        select(func.count()).select_from(model).where(model.family_id == family_id)
    )).scalar_one()


@pytest.mark.asyncio
async def test_apply_creates_everything(db_session, test_family, test_parent_user):
    pack = STARTER_PACKS["6-8"]
    result = await StarterPackService.apply(
        db_session, test_family.id, test_parent_user.id,
        StarterPackApplyRequest(age_band="6-8"),
    )
    assert result.created.chores == len(pack["chores"])
    assert result.created.gigs == len(pack["gigs"])
    assert result.created.rewards == len(pack["rewards"])
    assert result.skipped.chores == result.skipped.gigs == result.skipped.rewards == 0

    assert await _count(db_session, TaskTemplate, test_family.id) == len(pack["chores"])
    assert await _count(db_session, GigOffering, test_family.id) == len(pack["gigs"])
    assert await _count(db_session, Reward, test_family.id) == len(pack["rewards"])

    # Spanish titles by default on single-title models
    gig_titles = (await db_session.execute(
        select(GigOffering.title).where(GigOffering.family_id == test_family.id)
    )).scalars().all()
    assert set(gig_titles) == {g["title_es"] for g in pack["gigs"]}

    # Chore templates carry BOTH languages
    tpl = (await db_session.execute(
        select(TaskTemplate).where(TaskTemplate.family_id == test_family.id).limit(1)
    )).scalar_one()
    assert tpl.title and tpl.title_es
    assert tpl.is_bonus is False


@pytest.mark.asyncio
async def test_apply_is_idempotent(db_session, test_family, test_parent_user):
    req = StarterPackApplyRequest(age_band="9-12")
    first = await StarterPackService.apply(
        db_session, test_family.id, test_parent_user.id, req
    )
    second = await StarterPackService.apply(
        db_session, test_family.id, test_parent_user.id, req
    )
    assert second.created.chores == second.created.gigs == second.created.rewards == 0
    assert second.skipped.chores == first.created.chores
    assert second.skipped.gigs == first.created.gigs
    assert second.skipped.rewards == first.created.rewards
    # No duplicate rows
    pack = STARTER_PACKS["9-12"]
    assert await _count(db_session, TaskTemplate, test_family.id) == len(pack["chores"])
    assert await _count(db_session, GigOffering, test_family.id) == len(pack["gigs"])
    assert await _count(db_session, Reward, test_family.id) == len(pack["rewards"])


@pytest.mark.asyncio
async def test_apply_skips_matching_manual_titles(
    db_session, test_family, test_parent_user
):
    """A parent-created row with the same title (either language, any case)
    blocks the pack duplicate but nothing else."""
    pack = STARTER_PACKS["6-8"]
    db_session.add(Reward(
        title=pack["rewards"][0]["title_es"].upper(),  # case-insensitive match
        points_cost=99,
        category=RewardCategory.TREATS,
        family_id=test_family.id,
    ))
    await db_session.commit()

    result = await StarterPackService.apply(
        db_session, test_family.id, test_parent_user.id,
        StarterPackApplyRequest(age_band="6-8"),
    )
    assert result.skipped.rewards == 1
    assert result.created.rewards == len(pack["rewards"]) - 1


@pytest.mark.asyncio
async def test_apply_is_family_scoped(db_session, test_family, test_parent_user):
    """Family B applying the same pack creates its own rows — A's titles
    don't shadow B, and B's rows carry B's family_id."""
    from app.models.family import Family
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    family_b = Family(name="Other Family")
    db_session.add(family_b)
    await db_session.commit()
    await db_session.refresh(family_b)
    parent_b = User(
        email="parentb@test.com",
        password_hash=get_password_hash("password123"),
        name="Parent B",
        role=UserRole.PARENT,
        family_id=family_b.id,
        email_verified=True,
        points=0,
    )
    db_session.add(parent_b)
    await db_session.commit()
    await db_session.refresh(parent_b)

    req = StarterPackApplyRequest(age_band="3-5")
    res_a = await StarterPackService.apply(
        db_session, test_family.id, test_parent_user.id, req
    )
    res_b = await StarterPackService.apply(
        db_session, family_b.id, parent_b.id, req
    )
    pack = STARTER_PACKS["3-5"]
    assert res_a.created.chores == res_b.created.chores == len(pack["chores"])
    assert await _count(db_session, TaskTemplate, test_family.id) == len(pack["chores"])
    assert await _count(db_session, TaskTemplate, family_b.id) == len(pack["chores"])
    assert await _count(db_session, Reward, family_b.id) == len(pack["rewards"])


@pytest.mark.asyncio
async def test_apply_subset_selection(db_session, test_family, test_parent_user):
    pack = STARTER_PACKS["13+"]
    chore_ids = [c["id"] for c in pack["chores"][:2]]
    result = await StarterPackService.apply(
        db_session, test_family.id, test_parent_user.id,
        StarterPackApplyRequest(
            age_band="13+",
            chore_ids=chore_ids,
            gig_ids=[],            # explicit none
            reward_ids=None,       # omitted → all
        ),
    )
    assert result.created.chores == 2
    assert result.created.gigs == 0
    assert result.created.rewards == len(pack["rewards"])
    assert await _count(db_session, GigOffering, test_family.id) == 0


@pytest.mark.asyncio
async def test_apply_unknown_ids_ignored(db_session, test_family, test_parent_user):
    result = await StarterPackService.apply(
        db_session, test_family.id, test_parent_user.id,
        StarterPackApplyRequest(
            age_band="6-8",
            chore_ids=["nope.not-real"], gig_ids=["x"], reward_ids=["y"],
        ),
    )
    assert result.created.chores == 0
    assert result.created.gigs == 0
    assert result.created.rewards == 0


@pytest.mark.asyncio
async def test_apply_english_titles(db_session, test_family, test_parent_user):
    pack = STARTER_PACKS["6-8"]
    await StarterPackService.apply(
        db_session, test_family.id, test_parent_user.id,
        StarterPackApplyRequest(age_band="6-8", lang="en"),
    )
    reward_titles = (await db_session.execute(
        select(Reward.title).where(Reward.family_id == test_family.id)
    )).scalars().all()
    assert set(reward_titles) == {r["title_en"] for r in pack["rewards"]}


@pytest.mark.asyncio
async def test_apply_advances_onboarding_checklist(
    db_session, test_family, test_parent_user
):
    await StarterPackService.apply(
        db_session, test_family.id, test_parent_user.id,
        StarterPackApplyRequest(age_band="3-5"),
    )
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.task_created is True
    assert state.reward_created is True


@pytest.mark.asyncio
async def test_apply_unknown_band_rejected(db_session, test_family, test_parent_user):
    with pytest.raises(ValidationException):
        await StarterPackService.apply(
            db_session, test_family.id, test_parent_user.id,
            StarterPackApplyRequest(age_band="99+"),
        )


# ── Routes: parent-only gating ───────────────────────────────────────────────

@pytest_asyncio.fixture
async def parent_client(client, test_parent_user):
    r = await client.post("/api/auth/login", json={
        "email": "parent@test.com", "password": "password123",
    })
    assert r.status_code == 200
    client.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return client


@pytest_asyncio.fixture
async def child_client(client, test_child_user):
    r = await client.post("/api/auth/login", json={
        "email": "child@test.com", "password": "password123",
    })
    assert r.status_code == 200
    client.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return client


@pytest.mark.asyncio
async def test_route_list_packs(parent_client):
    r = await parent_client.get("/api/families/onboarding/starter-packs")
    assert r.status_code == 200
    packs = r.json()["packs"]
    assert [p["age_band"] for p in packs] == list(STARTER_PACKS.keys())
    assert all(len(p["chores"]) >= 8 for p in packs)


@pytest.mark.asyncio
async def test_route_apply_then_reapply(parent_client, db_session, test_family):
    body = {"age_band": "6-8", "lang": "es"}
    r = await parent_client.post(
        "/api/families/onboarding/starter-packs/apply", json=body
    )
    assert r.status_code == 200
    data = r.json()
    assert data["created"]["chores"] == len(STARTER_PACKS["6-8"]["chores"])

    r2 = await parent_client.post(
        "/api/families/onboarding/starter-packs/apply", json=body
    )
    assert r2.status_code == 200
    assert r2.json()["created"] == {"chores": 0, "gigs": 0, "rewards": 0}


@pytest.mark.asyncio
async def test_route_apply_unknown_band_400(parent_client):
    r = await parent_client.post(
        "/api/families/onboarding/starter-packs/apply",
        json={"age_band": "banda-falsa"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_route_child_forbidden(child_client):
    r = await child_client.get("/api/families/onboarding/starter-packs")
    assert r.status_code == 403
    r2 = await child_client.post(
        "/api/families/onboarding/starter-packs/apply",
        json={"age_band": "6-8"},
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_route_requires_auth(client):
    r = await client.get("/api/families/onboarding/starter-packs")
    assert r.status_code in (401, 403)
