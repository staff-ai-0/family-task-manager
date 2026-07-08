"""P1-KIOSK: member colors, kiosk PINs, per-kid PIN view, leaderboard.

Member prefs live in Redis (family_settings:{fid}:member_prefs); every
test family gets a fresh UUID so keys never collide across runs.
"""

import pytest
import pytest_asyncio

from app.models.kiosk_device import KioskDevice
from app.services.member_prefs_service import (
    MEMBER_COLORS,
    MemberPrefsService,
    default_color_name,
)


@pytest_asyncio.fixture
async def parent_client(client, test_parent_user):
    r = await client.post("/api/auth/login", json={
        "email": "parent@test.com", "password": "password123",
    })
    assert r.status_code == 200
    client.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return client


@pytest_asyncio.fixture
async def kiosk_device(db_session, test_family):
    d = KioskDevice(
        family_id=test_family.id, name="Hall", token="kiosktesttoken" * 4
    )
    db_session.add(d)
    await db_session.commit()
    await db_session.refresh(d)
    return d


class TestMemberColors:
    def test_default_color_deterministic(self, ):
        import uuid
        uid = uuid.uuid4()
        assert default_color_name(uid) == default_color_name(str(uid))
        assert default_color_name(uid) in MEMBER_COLORS

    @pytest.mark.asyncio
    async def test_list_member_prefs_defaults(
        self, parent_client, test_parent_user, test_child_user
    ):
        r = await parent_client.get("/api/kiosk/member-prefs")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 2
        for row in rows:
            assert row["color"] in MEMBER_COLORS
            assert row["color_hex"] == MEMBER_COLORS[row["color"]]
            assert row["has_pin"] is False

    @pytest.mark.asyncio
    async def test_set_color(self, parent_client, test_child_user):
        r = await parent_client.put(
            f"/api/kiosk/member-prefs/{test_child_user.id}",
            json={"color": "coral"},
        )
        assert r.status_code == 200
        assert r.json()["color"] == "coral"
        assert r.json()["color_hex"] == "#FF8A65"

    @pytest.mark.asyncio
    async def test_set_invalid_color_rejected(self, parent_client, test_child_user):
        r = await parent_client.put(
            f"/api/kiosk/member-prefs/{test_child_user.id}",
            json={"color": "hotpink"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_colors_endpoint_any_member(self, client, test_child_user):
        r = await client.post("/api/auth/login", json={
            "email": "child@test.com", "password": "password123",
        })
        token = r.json()["access_token"]
        r = await client.get(
            "/api/users/colors", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        rows = r.json()
        assert any(row["user_id"] == str(test_child_user.id) for row in rows)
        assert all(row["color"].startswith("#") for row in rows)

    @pytest.mark.asyncio
    async def test_member_prefs_requires_parent(self, client, test_child_user):
        r = await client.post("/api/auth/login", json={
            "email": "child@test.com", "password": "password123",
        })
        token = r.json()["access_token"]
        r = await client.get(
            "/api/kiosk/member-prefs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403


class TestKioskPin:
    @pytest.mark.asyncio
    async def test_set_pin_and_flag(self, parent_client, test_child_user):
        r = await parent_client.put(
            f"/api/kiosk/member-prefs/{test_child_user.id}",
            json={"pin": "1234"},
        )
        assert r.status_code == 200
        assert r.json()["has_pin"] is True

        # Clear it
        r = await parent_client.put(
            f"/api/kiosk/member-prefs/{test_child_user.id}",
            json={"pin": ""},
        )
        assert r.status_code == 200
        assert r.json()["has_pin"] is False

    @pytest.mark.asyncio
    async def test_non_numeric_pin_rejected(self, parent_client, test_child_user):
        r = await parent_client.put(
            f"/api/kiosk/member-prefs/{test_child_user.id}",
            json={"pin": "abcd"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_pin_view_flow(
        self, parent_client, test_family, test_child_user, kiosk_device
    ):
        # Parent sets the kid's PIN
        r = await parent_client.put(
            f"/api/kiosk/member-prefs/{test_child_user.id}",
            json={"pin": "4321"},
        )
        assert r.status_code == 200

        # Bad token → 401
        r = await parent_client.post("/api/kiosk/pin-view", json={
            "token": "not-a-real-token-xx",
            "user_id": str(test_child_user.id),
            "pin": "4321",
        })
        assert r.status_code == 401

        # Wrong PIN → 403
        r = await parent_client.post("/api/kiosk/pin-view", json={
            "token": kiosk_device.token,
            "user_id": str(test_child_user.id),
            "pin": "0000",
        })
        assert r.status_code == 403

        # Correct PIN → kid view
        r = await parent_client.post("/api/kiosk/pin-view", json={
            "token": kiosk_device.token,
            "user_id": str(test_child_user.id),
            "pin": "4321",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == test_child_user.name
        assert data["points"] == 100
        assert data["cash_cents"] == 0
        assert isinstance(data["chores"], list)
        assert data["color_hex"].startswith("#")

    @pytest.mark.asyncio
    async def test_pin_view_gigs_open_counts_claimable_only(
        self,
        parent_client,
        db_session,
        test_family,
        test_parent_user,
        test_child_user,
        test_teen_user,
        kiosk_device,
    ):
        """gigs_open = gigs THIS kid could claim right now: excludes
        role-restricted boards entries, inactive offerings, and gigs the
        kid already holds an open claim on — but a SIBLING's claim does
        not reduce the count (multi-claim is allowed per gig+user)."""
        from app.models.gig import GigClaim, GigClaimStatus, GigOffering

        def offering(title, **kw):
            return GigOffering(
                family_id=test_family.id,
                created_by=test_parent_user.id,
                title=title,
                points=10,
                **kw,
            )

        o_open = offering("Open to all")
        o_teen_only = offering("Teens only", allowed_roles=["teen"])
        o_mine = offering("Already mine")
        o_inactive = offering("Retired", is_active=False)
        o_sibling = offering("Sibling claimed")
        db_session.add_all([o_open, o_teen_only, o_mine, o_inactive, o_sibling])
        await db_session.commit()
        db_session.add_all([
            GigClaim(
                gig_id=o_mine.id,
                family_id=test_family.id,
                claimed_by=test_child_user.id,
                status=GigClaimStatus.CLAIMED,
            ),
            GigClaim(
                gig_id=o_sibling.id,
                family_id=test_family.id,
                claimed_by=test_teen_user.id,
                status=GigClaimStatus.CLAIMED,
            ),
        ])
        await db_session.commit()

        await MemberPrefsService.update_member_prefs(
            test_family.id, test_child_user.id, pin="2468"
        )
        r = await parent_client.post("/api/kiosk/pin-view", json={
            "token": kiosk_device.token,
            "user_id": str(test_child_user.id),
            "pin": "2468",
        })
        assert r.status_code == 200
        # o_open + o_sibling count; teen-only, inactive, and own-claim don't.
        assert r.json()["gigs_open"] == 2

    @pytest.mark.asyncio
    async def test_pin_view_no_pin_set(
        self, parent_client, test_child_user, kiosk_device
    ):
        r = await parent_client.post("/api/kiosk/pin-view", json={
            "token": kiosk_device.token,
            "user_id": str(test_child_user.id),
            "pin": "1111",
        })
        assert r.status_code == 403
        assert "not set" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_pin_throttle(
        self, parent_client, test_family, test_child_user, kiosk_device
    ):
        await MemberPrefsService.update_member_prefs(
            test_family.id, test_child_user.id, pin="9999"
        )
        for _ in range(5):
            r = await parent_client.post("/api/kiosk/pin-view", json={
                "token": kiosk_device.token,
                "user_id": str(test_child_user.id),
                "pin": "0001",
            })
            assert r.status_code == 403
        # 6th attempt — even with the RIGHT pin — is throttled
        r = await parent_client.post("/api/kiosk/pin-view", json={
            "token": kiosk_device.token,
            "user_id": str(test_child_user.id),
            "pin": "9999",
        })
        assert r.status_code == 429
        # cleanup so other tests on this (device, user) aren't affected
        await MemberPrefsService.clear_pin_failures(
            kiosk_device.id, test_child_user.id
        )


class TestSnapshotEnrichment:
    @pytest.mark.asyncio
    async def test_snapshot_has_colors_and_leaderboard(
        self, client, test_family, test_parent_user, test_child_user, kiosk_device
    ):
        r = await client.get(
            f"/api/kiosk/snapshot?token={kiosk_device.token}"
        )
        assert r.status_code == 200
        data = r.json()
        assert "leaderboard" in data
        assert "week_start" in data
        for m in data["members"]:
            assert m["color_hex"].startswith("#")
            assert "has_pin" in m
        # child is on the leaderboard even at 0 points; parent (0 pts) is not
        lb_ids = {e["user_id"] for e in data["leaderboard"]}
        assert str(test_child_user.id) in lb_ids
        assert str(test_parent_user.id) not in lb_ids

    @pytest.mark.asyncio
    async def test_leaderboard_counts_week_points(
        self, client, db_session, test_family, test_child_user, kiosk_device
    ):
        from datetime import datetime, timezone
        from app.models.point_transaction import PointTransaction, TransactionType

        db_session.add(PointTransaction(
            type=TransactionType.BONUS,
            points=25,
            user_id=test_child_user.id,
            balance_before=100,
            balance_after=125,
            created_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        r = await client.get(
            f"/api/kiosk/snapshot?token={kiosk_device.token}"
        )
        assert r.status_code == 200
        entry = next(
            e for e in r.json()["leaderboard"]
            if e["user_id"] == str(test_child_user.id)
        )
        assert entry["points_week"] == 25


class TestOnboardingFlyerStep:
    @pytest.mark.asyncio
    async def test_flyer_scanned_derived(self, db_session, test_family, test_parent_user):
        from app.models.calendar_event import CalendarEvent
        from app.services.onboarding_service import OnboardingService
        from datetime import datetime, timezone

        state = await OnboardingService.get_state(test_family.id, db_session)
        assert state.flyer_scanned is False

        db_session.add(CalendarEvent(
            family_id=test_family.id,
            title="Festival escolar",
            start_ts=datetime.now(timezone.utc),
            all_day=True,
            source="ocr_flyer",
            created_by=test_parent_user.id,
        ))
        await db_session.commit()

        state = await OnboardingService.get_state(test_family.id, db_session)
        assert state.flyer_scanned is True
        # all_done must NOT depend on the optional flyer step
        assert state.all_done is False
