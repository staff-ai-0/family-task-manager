"""Profile switcher (UX-E4): switched-session tokens."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import update

from app.core.security import create_refresh_token, decode_token, get_password_hash
from app.models.family import Family
from app.models.user import User, UserRole
from app.services.member_prefs_service import (
    PIN_MAX_FAILURES,
    MemberPrefsService,
    _redis,
)


def _remaining(payload) -> timedelta:
    return datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - datetime.now(timezone.utc)


class TestSwitchedTokens:
    def test_switched_refresh_has_sw_claim_and_2h_exp(self):
        sw = decode_token(create_refresh_token("u1", 0, switched=True), expected_type="refresh")
        assert sw["sw"] is True
        assert _remaining(sw) <= timedelta(hours=2, seconds=60)
        assert _remaining(sw) > timedelta(hours=1)

        normal = decode_token(create_refresh_token("u1", 0), expected_type="refresh")
        assert "sw" not in normal
        assert _remaining(normal) > timedelta(days=29)

    async def test_refresh_endpoint_propagates_sw(self, client, test_parent_user):
        token = create_refresh_token(str(test_parent_user.id), test_parent_user.token_version, switched=True)
        r = await client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["switched"] is True
        assert decode_token(body["access_token"], expected_type="access")["sw"] is True
        new_refresh = decode_token(body["refresh_token"], expected_type="refresh")
        assert new_refresh["sw"] is True
        assert _remaining(new_refresh) <= timedelta(hours=2, seconds=60)

    async def test_refresh_endpoint_normal_unchanged(self, client, test_parent_user):
        token = create_refresh_token(str(test_parent_user.id), test_parent_user.token_version)
        r = await client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.json()
        assert body["switched"] is False
        assert "sw" not in decode_token(body["access_token"], expected_type="access")
        assert "sw" not in decode_token(body["refresh_token"], expected_type="refresh")


GENERIC = "Invalid profile or PIN"
PIN = "1234"


async def _switch_keys():
    r = await _redis()
    try:
        return sorted([k async for k in r.scan_iter("switch_pin_fails:*")])
    finally:
        await r.aclose()


async def _wipe_switch_keys():
    r = await _redis()
    try:
        async for k in r.scan_iter("switch_pin_fails:*"):
            await r.delete(k)
    finally:
        await r.aclose()


@pytest_asyncio.fixture(autouse=True)
async def _clean_redis():
    await _wipe_switch_keys()
    yield
    await _wipe_switch_keys()


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _login(client, email, password="password123"):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["refresh_token"]


async def _mk_user(db, family_id, email, role, **kw):
    u = User(
        email=email,
        password_hash=kw.pop("password_hash", get_password_hash("password123")),
        name=kw.pop("name", email.split("@")[0]),
        role=role,
        family_id=family_id,
        email_verified=True,
        points=0,
        **kw,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture
async def kid(db_session, test_family, test_child_user):
    await MemberPrefsService.update_member_prefs(test_family.id, test_child_user.id, pin=PIN)
    return test_child_user


@pytest_asyncio.fixture
async def home(client, test_parent_user):
    return await _login(client, "parent@test.com")


async def _switch(client, home_tok, user_id, pin=PIN):
    return await client.post(
        "/api/auth/profile/switch",
        json={"user_id": str(user_id), "pin": pin},
        headers=_bearer(home_tok),
    )


class TestProfileSwitch:
    async def test_list_returns_only_kids_and_teens_with_has_pin(
        self, client, home, kid, test_teen_user, test_parent_user_2
    ):
        r = await client.get("/api/auth/profile/list", headers=_bearer(home))
        assert r.status_code == 200
        body = r.json()
        by_id = {p["id"]: p for p in body["profiles"]}
        assert set(by_id) == {str(kid.id), str(test_teen_user.id)}
        assert by_id[str(kid.id)]["has_pin"] is True
        assert by_id[str(test_teen_user.id)]["has_pin"] is False
        assert by_id[str(kid.id)]["role"] == "child"
        assert by_id[str(kid.id)]["color"]
        assert decode_token(body["home_refresh_token"], expected_type="refresh")["sub"]

    async def test_switch_ok_returns_kid_pair_with_sw_and_rotated_home(
        self, client, home, kid, test_parent_user
    ):
        r = await _switch(client, home, kid.id)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["switched"] is True
        assert body["user"]["id"] == str(kid.id)
        acc = decode_token(body["access_token"], expected_type="access")
        assert acc["sub"] == str(kid.id) and acc["sw"] is True
        assert acc["family_id"] == str(kid.family_id)
        ref = decode_token(body["refresh_token"], expected_type="refresh")
        assert ref["sub"] == str(kid.id) and ref["sw"] is True
        h = decode_token(body["home_refresh_token"], expected_type="refresh")
        assert h["sub"] == str(test_parent_user.id)
        assert "sw" not in h
        assert body["home_refresh_token"] != home

    async def test_wrong_pin_403_same_detail(self, client, home, kid):
        r = await _switch(client, home, kid.id, pin="9999")
        assert r.status_code == 403
        assert r.json()["detail"] == GENERIC

    @pytest.mark.parametrize(
        "case",
        ["unknown", "parent", "other_family", "inactive", "unapproved", "deleted"],
    )
    async def test_unknown_parent_other_family_inactive_unapproved_deleted_targets_same_403(
        self, client, db_session, home, test_family, test_parent_user, case
    ):
        if case == "unknown":
            target = uuid.uuid4()
        elif case == "parent":
            target = test_parent_user.id
            await MemberPrefsService.update_member_prefs(test_family.id, target, pin=PIN)
        else:
            fam_id = test_family.id
            if case == "other_family":
                other = Family(name="Other")
                db_session.add(other)
                await db_session.commit()
                await db_session.refresh(other)
                fam_id = other.id
            extra = {}
            if case == "inactive":
                extra["is_active"] = False
            if case == "unapproved":
                extra["approval_status"] = "pending"
            if case == "deleted":
                extra["deleted_at"] = datetime.now(timezone.utc)
            u = await _mk_user(db_session, fam_id, f"{case}@kidmail.com", UserRole.CHILD, **extra)
            await MemberPrefsService.update_member_prefs(fam_id, u.id, pin=PIN)
            target = u.id
        r = await _switch(client, home, target)
        assert r.status_code == 403
        assert r.json()["detail"] == GENERIC
        assert await _switch_keys() == []

    async def test_no_pin_set_same_403(self, client, home, test_teen_user):
        r = await _switch(client, home, test_teen_user.id)
        assert r.status_code == 403
        assert r.json()["detail"] == GENERIC

    async def test_member_lockout_429_even_with_fresh_home_session(
        self, client, home, kid, test_parent_user_2
    ):
        for _ in range(PIN_MAX_FAILURES):
            r = await _switch(client, home, kid.id, pin="0000")
            assert r.status_code == 403
        home_b = await _login(client, "parent2@test.com")
        r = await _switch(client, home_b, kid.id, pin=PIN)
        assert r.status_code == 429
        assert r.json()["detail"] == "Too many attempts. Try again in a few minutes."
        # The original home is locked too, even with the right PIN.
        r = await _switch(client, home, kid.id, pin=PIN)
        assert r.status_code == 429

    async def test_pair_counter_cleared_on_success(self, client, home, kid, test_parent_user):
        for _ in range(2):
            await _switch(client, home, kid.id, pin="0000")
        assert len(await _switch_keys()) == 2
        r = await _switch(client, home, kid.id)
        assert r.status_code == 200
        assert await _switch_keys() == [f"switch_pin_fails:member:{kid.id}"]
        assert await MemberPrefsService.switch_failures(test_parent_user.id, kid.id) == 2

    async def test_kid_refresh_token_as_bearer_403(self, client, kid, test_teen_user):
        kid_tok = await _login(client, "child@test.com")
        r = await client.get("/api/auth/profile/list", headers=_bearer(kid_tok))
        assert r.status_code == 403
        r = await _switch(client, kid_tok, test_teen_user.id)
        assert r.status_code == 403
        r = await client.post(
            "/api/auth/profile/return", json={"password": "password123"}, headers=_bearer(kid_tok)
        )
        assert r.status_code == 403

    async def test_sw_token_rejected_as_home(self, client, kid, test_parent_user):
        sw = create_refresh_token(str(test_parent_user.id), test_parent_user.token_version, switched=True)
        r = await client.get("/api/auth/profile/list", headers=_bearer(sw))
        assert r.status_code == 403
        r = await _switch(client, sw, kid.id)
        assert r.status_code == 403

    async def test_teen_or_child_home_token_403(self, client, kid, test_teen_user):
        for email in ("child@test.com", "teen@test.com"):
            tok = await _login(client, email)
            r = await client.get("/api/auth/profile/list", headers=_bearer(tok))
            assert r.status_code == 403

    async def test_return_needs_password(self, client, home, test_parent_user):
        r = await client.post(
            "/api/auth/profile/return", json={"password": "nope"}, headers=_bearer(home)
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "Invalid password"
        r = await client.post(
            "/api/auth/profile/return", json={"password": "password123"}, headers=_bearer(home)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["switched"] is False
        assert body["user"]["id"] == str(test_parent_user.id)
        assert "sw" not in decode_token(body["access_token"], expected_type="access")
        assert "sw" not in decode_token(body["refresh_token"], expected_type="refresh")

    async def test_return_rejected_for_sw_token(self, client, test_parent_user):
        sw = create_refresh_token(str(test_parent_user.id), test_parent_user.token_version, switched=True)
        r = await client.post(
            "/api/auth/profile/return", json={"password": "password123"}, headers=_bearer(sw)
        )
        assert r.status_code == 403

    async def test_return_with_null_password_hash_403(self, client, db_session, home, test_parent_user):
        await db_session.execute(
            update(User).where(User.id == test_parent_user.id).values(password_hash=None)
        )
        await db_session.commit()
        r = await client.post(
            "/api/auth/profile/return", json={"password": "password123"}, headers=_bearer(home)
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "Invalid password"

    async def test_token_version_bump_invalidates_home_and_switched(
        self, client, db_session, home, kid, test_parent_user
    ):
        r = await _switch(client, home, kid.id)
        assert r.status_code == 200
        kid_refresh = r.json()["refresh_token"]
        await db_session.execute(
            update(User).where(User.id == kid.id).values(token_version=User.token_version + 1)
        )
        await db_session.commit()
        r = await client.post("/api/auth/refresh", headers=_bearer(kid_refresh))
        assert r.status_code == 401
        await db_session.execute(
            update(User)
            .where(User.id == test_parent_user.id)
            .values(token_version=User.token_version + 1)
        )
        await db_session.commit()
        r = await client.get("/api/auth/profile/list", headers=_bearer(home))
        assert r.status_code == 401

    async def test_passwordless_kid_can_be_switched_to_and_me_works(
        self, client, db_session, home, test_family
    ):
        u = await _mk_user(
            db_session, test_family.id, "nopass@kidmail.com", UserRole.CHILD, password_hash=None
        )
        await MemberPrefsService.update_member_prefs(test_family.id, u.id, pin=PIN)
        r = await _switch(client, home, u.id)
        assert r.status_code == 200, r.text
        me = await client.get("/api/auth/me", headers=_bearer(r.json()["access_token"]))
        assert me.status_code == 200
        assert me.json()["id"] == str(u.id)

    async def test_deactivated_parent_home_token_rejected(
        self, client, db_session, home, kid, test_parent_user
    ):
        from app.services.auth_service import AuthService

        await AuthService.deactivate_user(db_session, test_parent_user.id)
        r = await client.get("/api/auth/profile/list", headers=_bearer(home))
        assert r.status_code == 401
        r = await _switch(client, home, kid.id)
        assert r.status_code == 401

    async def test_unapproved_parent_home_token_rejected(
        self, client, db_session, home, kid, test_parent_user
    ):
        await db_session.execute(
            update(User).where(User.id == test_parent_user.id).values(approval_status="pending")
        )
        await db_session.commit()
        r = await client.get("/api/auth/profile/list", headers=_bearer(home))
        assert r.status_code == 401
        r = await _switch(client, home, kid.id)
        assert r.status_code == 401
