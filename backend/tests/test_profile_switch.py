"""Profile switcher (UX-E4): switched-session tokens."""
from datetime import datetime, timedelta, timezone

from app.core.security import create_refresh_token, decode_token


def _remaining(payload) -> timedelta:
    return datetime.fromtimestamp(payload["exp"], tz=timezone.utc) - datetime.now(timezone.utc)


class TestSwitchedTokens:
    def test_switched_refresh_has_sw_claim_and_2h_exp(self):
        sw = decode_token(create_refresh_token("u1", 0, switched=True), expected_type="refresh")
        assert sw["sw"] is True
        assert _remaining(sw) <= timedelta(hours=2, seconds=60)

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
