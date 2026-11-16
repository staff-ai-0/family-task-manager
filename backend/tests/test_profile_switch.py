"""Profile switcher (UX-E4): switched-session tokens."""
import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_home_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
)
from app.main import app
from app.models.family import Family
from app.models.user import User, UserRole
from app.services.member_prefs_service import (
    MEMBER_COLORS,
    PIN_FAILURE_WINDOW_SECONDS,
    PIN_MAX_FAILURES,
    MemberPrefsService,
    _redis,
    default_color_name,
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


async def _login_pair(client, email, password="password123"):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


async def _login(client, email, password="password123"):
    return (await _login_pair(client, email, password))["refresh_token"]


async def _share(client, email) -> str:
    """The real path to a home token: parent access token -> profile/share."""
    access = (await _login_pair(client, email))["access_token"]
    r = await client.post("/api/auth/profile/share", headers=_bearer(access))
    assert r.status_code == 200, r.text
    return r.json()["home_token"]


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
    return await _share(client, "parent@test.com")


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
        assert "home_refresh_token" not in body
        assert decode_token(body["home_token"], expected_type="home")["sub"]

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
        assert "home_refresh_token" not in body
        h = decode_token(body["home_token"], expected_type="home")
        assert h["sub"] == str(test_parent_user.id)
        assert "sw" not in h
        assert body["home_token"] != home

    async def test_list_colors_are_hex_the_picker_can_paint(
        self, client, home, kid, test_family, test_teen_user
    ):
        await MemberPrefsService.update_member_prefs(test_family.id, kid.id, color="mint")
        r = await client.get("/api/auth/profile/list", headers=_bearer(home))
        assert r.status_code == 200
        by_id = {p["id"]: p for p in r.json()["profiles"]}
        assert by_id[str(kid.id)]["color"] == MEMBER_COLORS["mint"]
        teen_color = by_id[str(test_teen_user.id)]["color"]
        assert re.fullmatch(r"#[0-9A-Fa-f]{6}", teen_color)
        assert teen_color == MEMBER_COLORS[default_color_name(test_teen_user.id)]

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
        home_b = await _share(client, "parent2@test.com")
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

    async def test_kid_refresh_token_as_bearer_401(self, client, kid, test_teen_user):
        # A kid's own refresh token is not a home token: wrong type, 401.
        kid_tok = await _login(client, "child@test.com")
        r = await client.get("/api/auth/profile/list", headers=_bearer(kid_tok))
        assert r.status_code == 401
        r = await _switch(client, kid_tok, test_teen_user.id)
        assert r.status_code == 401
        r = await client.post(
            "/api/auth/profile/return", json={"password": "password123"}, headers=_bearer(kid_tok)
        )
        assert r.status_code == 401

    async def test_sw_token_rejected_as_home(self, client, kid, test_parent_user):
        sw = create_refresh_token(str(test_parent_user.id), test_parent_user.token_version, switched=True)
        r = await client.get("/api/auth/profile/list", headers=_bearer(sw))
        assert r.status_code == 401
        r = await _switch(client, sw, kid.id)
        assert r.status_code == 401

    async def test_teen_or_child_home_token_403(self, client, kid, test_child_user, test_teen_user):
        # Defence in depth: share only mints home tokens for parents, but a
        # home-typed token for a kid must still be refused by role.
        for u in (test_child_user, test_teen_user):
            tok = create_home_token(str(u.id), u.token_version)
            r = await client.get("/api/auth/profile/list", headers=_bearer(tok))
            assert r.status_code == 403
            r = await _switch(client, tok, kid.id)
            assert r.status_code == 403
            r = await client.post(
                "/api/auth/profile/return", json={"password": "password123"}, headers=_bearer(tok)
            )
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
        assert r.status_code == 401

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


class TestHomeTokenIsNotARefreshToken:
    """C1: ftm_home is visible to anyone holding the device (DevTools). Its
    token must be useless outside profile/*: a teen who copies it must not get
    a parent session from /api/auth/refresh or any access-token route."""

    def test_home_token_claims_and_type(self, test_parent_user):
        tok = create_home_token(str(test_parent_user.id), 3)
        p = decode_token(tok, expected_type="home")
        assert p["type"] == "home"
        assert p["sub"] == str(test_parent_user.id)
        assert p["ver"] == 3
        assert p["jti"]
        assert "sw" not in p
        assert _remaining(p) > timedelta(days=29)
        assert _remaining(p) <= timedelta(days=30, seconds=60)
        for other in ("refresh", "access"):
            with pytest.raises(HTTPException) as exc:
                decode_token(tok, expected_type=other)
            assert exc.value.status_code == 401

    async def test_home_token_rejected_at_refresh(self, client, home):
        r = await client.post("/api/auth/refresh", headers=_bearer(home))
        assert r.status_code == 401
        assert "access_token" not in r.json()

    async def test_home_token_rejected_at_me(self, client, home):
        r = await client.get("/api/auth/me", headers=_bearer(home))
        assert r.status_code == 401

    @pytest.mark.parametrize("kind", ["refresh", "access"])
    async def test_parent_session_tokens_rejected_at_profile_routes(
        self, client, kid, test_parent_user, kind
    ):
        tok = (await _login_pair(client, "parent@test.com"))[f"{kind}_token"]
        r = await client.get("/api/auth/profile/list", headers=_bearer(tok))
        assert r.status_code == 401
        r = await _switch(client, tok, kid.id)
        assert r.status_code == 401
        r = await client.post(
            "/api/auth/profile/return", json={"password": "password123"}, headers=_bearer(tok)
        )
        assert r.status_code == 401


class TestProfileShare:
    async def test_parent_gets_home_token_that_works_at_list(self, client, kid, test_parent_user):
        access = (await _login_pair(client, "parent@test.com"))["access_token"]
        r = await client.post("/api/auth/profile/share", headers=_bearer(access))
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"home_token"}
        p = decode_token(body["home_token"], expected_type="home")
        assert p["sub"] == str(test_parent_user.id)
        assert p["ver"] == test_parent_user.token_version
        r = await client.get("/api/auth/profile/list", headers=_bearer(body["home_token"]))
        assert r.status_code == 200
        assert str(kid.id) in {e["id"] for e in r.json()["profiles"]}

    @pytest.mark.parametrize("email", ["child@test.com", "teen@test.com"])
    async def test_kid_access_token_403(self, client, test_child_user, test_teen_user, email):
        access = (await _login_pair(client, email))["access_token"]
        r = await client.post("/api/auth/profile/share", headers=_bearer(access))
        assert r.status_code == 403
        assert "home_token" not in r.json()

    async def test_switched_access_token_403(self, client, home, kid, test_parent_user):
        # A real switched kid session...
        r = await _switch(client, home, kid.id)
        assert r.status_code == 200
        r = await client.post(
            "/api/auth/profile/share", headers=_bearer(r.json()["access_token"])
        )
        assert r.status_code == 403
        # ...and the sw guard on its own (a PARENT-role token carrying sw), so
        # the role check cannot mask a missing sw check.
        sw = create_access_token(
            {
                "sub": str(test_parent_user.id),
                "role": "parent",
                "family_id": str(test_parent_user.family_id),
                "sw": True,
            }
        )
        r = await client.post("/api/auth/profile/share", headers=_bearer(sw))
        assert r.status_code == 403

    async def test_unauthenticated_401(self, client):
        r = await client.post("/api/auth/profile/share")
        assert r.status_code == 401

    async def test_unapproved_parent_with_live_access_token_403(
        self, client, db_session, test_parent_user
    ):
        # get_current_user does not check approval_status; share must.
        access = (await _login_pair(client, "parent@test.com"))["access_token"]
        await db_session.execute(
            update(User).where(User.id == test_parent_user.id).values(approval_status="pending")
        )
        await db_session.commit()
        r = await client.post("/api/auth/profile/share", headers=_bearer(access))
        assert r.status_code == 403
        assert "home_token" not in r.json()

    async def test_refresh_or_home_token_as_bearer_401(self, client, home, test_parent_user):
        refresh = await _login(client, "parent@test.com")
        for tok in (refresh, home):
            r = await client.post("/api/auth/profile/share", headers=_bearer(tok))
            assert r.status_code == 401


def _member_key(member_id) -> str:
    return f"switch_pin_fails:member:{member_id}"


def _pair_key(home_id, member_id) -> str:
    return f"switch_pin_fails:pair:{home_id}:{member_id}"


async def _redis_get_ttl(key):
    r = await _redis()
    try:
        return await r.get(key), await r.ttl(key)
    finally:
        await r.aclose()


class TestPinThrottleReserveFirst:
    """I2: the attempt is counted BEFORE the PIN is checked, atomically, so
    concurrent guesses cannot all pass a read-then-check gate, and a key can
    never be left without a TTL (which would lock the member forever)."""

    async def test_concurrent_wrong_pins_reach_the_pin_check_at_most_cap_times(
        self, client, test_engine, home, kid, monkeypatch
    ):
        # Concurrent requests cannot share the fixture's single session.
        maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

        async def per_request_db():
            async with maker() as s:
                yield s

        app.dependency_overrides[get_db] = per_request_db

        checked = 0

        async def slow_wrong_pin(family_id, user_id, pin):
            nonlocal checked
            checked += 1
            await asyncio.sleep(0.2)  # hold the race window wide open
            return False

        monkeypatch.setattr(MemberPrefsService, "verify_member_pin", staticmethod(slow_wrong_pin))
        n = PIN_MAX_FAILURES + 5
        rs = await asyncio.gather(*[_switch(client, home, kid.id, pin="0000") for _ in range(n)])
        codes = [r.status_code for r in rs]
        assert checked == PIN_MAX_FAILURES
        assert codes.count(403) == PIN_MAX_FAILURES
        assert codes.count(429) == n - PIN_MAX_FAILURES

    async def test_both_keys_always_carry_a_ttl(self, client, home, kid, test_parent_user):
        r = await _switch(client, home, kid.id, pin="0000")
        assert r.status_code == 403
        for key in (_member_key(kid.id), _pair_key(test_parent_user.id, kid.id)):
            val, ttl = await _redis_get_ttl(key)
            assert val == "1"
            assert 0 < ttl <= PIN_FAILURE_WINDOW_SECONDS

    async def test_failure_between_incr_and_expire_never_leaves_a_ttl_less_key(
        self, client, home, kid, monkeypatch
    ):
        def boom(self, *a, **kw):
            raise RedisConnectionError("lost the connection after INCR")

        monkeypatch.setattr(aioredis.Redis, "expire", boom)
        with pytest.raises(RedisConnectionError):
            await _switch(client, home, kid.id, pin="0000")
        monkeypatch.undo()
        for key in await _switch_keys():
            _, ttl = await _redis_get_ttl(key)
            assert ttl > 0, f"{key} has no TTL: the member would be locked forever"

    async def test_success_refunds_its_own_reservation(self, client, home, kid, test_parent_user):
        r = await _switch(client, home, kid.id)
        assert r.status_code == 200
        val, _ = await _redis_get_ttl(_member_key(kid.id))
        assert int(val or 0) == 0
        assert (await _redis_get_ttl(_pair_key(test_parent_user.id, kid.id)))[0] is None

    async def test_a_success_frees_the_slot_it_used(self, client, home, kid):
        for _ in range(PIN_MAX_FAILURES - 1):
            assert (await _switch(client, home, kid.id, pin="0000")).status_code == 403
        assert (await _switch(client, home, kid.id)).status_code == 200
        # Refunded: one more guess is still allowed, the next one is locked.
        assert (await _switch(client, home, kid.id, pin="0000")).status_code == 403
        assert (await _switch(client, home, kid.id, pin="0000")).status_code == 429

    async def test_refund_never_goes_below_zero_or_creates_a_key(self, test_parent_user, kid):
        await MemberPrefsService.refund_switch_attempt(test_parent_user.id, kid.id)
        assert await _switch_keys() == []
        member, pair = await MemberPrefsService.reserve_switch_attempt(test_parent_user.id, kid.id)
        assert (member, pair) == (1, 1)
        await MemberPrefsService.refund_switch_attempt(test_parent_user.id, kid.id)
        await MemberPrefsService.refund_switch_attempt(test_parent_user.id, kid.id)
        val, ttl = await _redis_get_ttl(_member_key(kid.id))
        assert val == "0"
        assert ttl > 0
