"""Per-family module registry — enabled_modules on families + /auth/me.

NULL = all modules on (every pre-feature family). PATCH /api/families/me
accepts a subset of TOGGLABLE_MODULES (parent only); /auth/me denormalizes
the stored value so the SSR middleware payload can gate nav.
"""
import pytest

from app.core.modules import TOGGLABLE_MODULES, effective_modules


# ── pure helper ───────────────────────────────────────────────────────────


def test_effective_modules_null_means_all_on():
    assert effective_modules(None) == set(TOGGLABLE_MODULES)


def test_effective_modules_filters_unknown_keys():
    assert effective_modules(["meals", "bogus"]) == {"meals"}


def test_togglable_set_is_the_seven_optional_surfaces():
    assert TOGGLABLE_MODULES == {
        "meals", "shopping", "calendar", "pet", "chat", "budget", "gigs"
    }


# ── API ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_is_null_all_on(client, auth_headers, test_family):
    r = await client.get("/api/families/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["enabled_modules"] is None

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.status_code == 200
    assert me.json()["enabled_modules"] is None


@pytest.mark.asyncio
async def test_patch_subset_persists_and_reaches_me(client, auth_headers):
    r = await client.patch(
        "/api/families/me",
        json={"enabled_modules": ["meals", "shopping", "gigs"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled_modules"] == ["gigs", "meals", "shopping"]  # sorted+dedup

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert sorted(me.json()["enabled_modules"]) == ["gigs", "meals", "shopping"]


@pytest.mark.asyncio
async def test_patch_empty_list_disables_all_togglables(client, auth_headers):
    r = await client.patch(
        "/api/families/me", json={"enabled_modules": []}, headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["enabled_modules"] == []


@pytest.mark.asyncio
async def test_patch_unknown_module_422(client, auth_headers):
    r = await client.patch(
        "/api/families/me",
        json={"enabled_modules": ["meals", "casino"]},
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert "casino" in r.text


@pytest.mark.asyncio
async def test_kid_cannot_patch_modules(client, test_child_user):
    login = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    token = login.json()["access_token"]
    r = await client.patch(
        "/api/families/me",
        json={"enabled_modules": ["meals"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
