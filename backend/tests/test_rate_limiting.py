"""B1: auth endpoints must be rate limited (brute-force / enumeration defense).

Before: no endpoint had any rate limit. A burst of login attempts from one client
must start returning 429 once the per-window limit is exceeded.

WS-F1: the limiter keys on CF-Connecting-IP (edge-set by Cloudflare, not
client-forgeable through the tunnel) and falls back to request.client.host.
X-Forwarded-For must NOT influence the key — Cloudflare appends to the
client-supplied list, so the leftmost entry is attacker-chosen.
"""
import pytest
from starlette.requests import Request as StarletteRequest

from app.core.rate_limiter import get_client_ip, limiter


def _make_request(headers: dict | None = None, client_host: str = "10.0.0.5"):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "query_string": b"",
        "client": (client_host, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return StarletteRequest(scope)


@pytest.fixture(autouse=True)
def _enable_rate_limiter():
    """This module needs the limiter ON (conftest disables it elsewhere)."""
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_login_burst_is_rate_limited(self, client):
        statuses = []
        for _ in range(13):
            r = await client.post(
                "/api/auth/login",
                json={"email": "nobody@test.com", "password": "wrong"},
            )
            statuses.append(r.status_code)
        assert 429 in statuses, f"expected a 429 once the limit is hit; got {statuses}"

    @pytest.mark.asyncio
    async def test_forgot_password_burst_is_rate_limited(self, client):
        statuses = []
        for _ in range(13):
            r = await client.post(
                "/api/auth/forgot-password", json={"email": "nobody@test.com"}
            )
            statuses.append(r.status_code)
        assert 429 in statuses, f"expected a 429 once the limit is hit; got {statuses}"


class TestLimiterKeyFunction:
    """get_client_ip: CF-Connecting-IP preferred, client.host fallback, XFF ignored."""

    def test_prefers_cf_connecting_ip(self):
        req = _make_request(
            headers={
                "CF-Connecting-IP": "203.0.113.9",
                "X-Forwarded-For": "6.6.6.6, 203.0.113.9",
            },
            client_host="10.89.0.4",
        )
        assert get_client_ip(req) == "203.0.113.9"

    def test_falls_back_to_client_host_without_cf_header(self):
        req = _make_request(client_host="10.0.0.5")
        assert get_client_ip(req) == "10.0.0.5"

    def test_ignores_x_forwarded_for(self):
        """XFF alone must not move the key off the socket peer address."""
        req = _make_request(
            headers={"X-Forwarded-For": "6.6.6.6"}, client_host="10.0.0.5"
        )
        assert get_client_ip(req) == "10.0.0.5"

    def test_blank_cf_header_falls_back(self):
        req = _make_request(
            headers={"CF-Connecting-IP": "  "}, client_host="10.0.0.5"
        )
        assert get_client_ip(req) == "10.0.0.5"


class TestRateLimitKeyBehavior:
    """Route-level proof that the limit is keyed per CF-Connecting-IP."""

    @pytest.mark.asyncio
    async def test_rotating_xff_does_not_evade_limit(self, client):
        """Same CF-Connecting-IP + rotating XFF must still trip the limit
        (this was the pre-fix bypass: rotate the leftmost XFF entry)."""
        statuses = []
        for i in range(13):
            r = await client.post(
                "/api/auth/login",
                json={"email": "nobody@test.com", "password": "wrong"},
                headers={
                    "CF-Connecting-IP": "203.0.113.9",
                    "X-Forwarded-For": f"198.51.100.{i}",
                },
            )
            statuses.append(r.status_code)
        assert 429 in statuses, f"rotating XFF evaded the limit: {statuses}"

    @pytest.mark.asyncio
    async def test_distinct_cf_ips_have_distinct_windows(self, client):
        """Different real clients (distinct CF-Connecting-IP) must not share
        one bucket — 13 requests from 13 IPs stay under the 10/min limit."""
        statuses = []
        for i in range(13):
            r = await client.post(
                "/api/auth/login",
                json={"email": "nobody@test.com", "password": "wrong"},
                headers={"CF-Connecting-IP": f"203.0.113.{i}"},
            )
            statuses.append(r.status_code)
        assert 429 not in statuses, f"distinct CF IPs shared a bucket: {statuses}"
