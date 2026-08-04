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


_ATTACKER_IP = "203.0.113.77"
_REDEEM = "/api/subscriptions/coupons/redeem"


async def _signup(client, email: str, *, coupon: str | None = None, ip: str):
    body = {
        "family_name": "Los Nuevos",
        "name": "Ana",
        "email": email,
        "password": "password123",
        "accept_terms": True,
    }
    if coupon is not None:
        body["coupon"] = coupon
    return await client.post(
        "/api/auth/register-family", json=body, headers={"CF-Connecting-IP": ip}
    )


async def _redeem(client, auth_headers, *, ip: str):
    return await client.post(
        _REDEEM,
        json={"code": "GUESS"},
        headers={**auth_headers, "CF-Connecting-IP": ip},
    )


class TestCouponAttemptBudget:
    """A coupon guess costs the same scarce budget wherever it enters from.

    The dedicated endpoint is COUPON_LIMIT (10/hour), but register-family
    reaches the SAME CouponService.redeem while carrying only AUTH_LIMIT
    (10/minute = 600/hour) — a 60x budget against codes the coupon service's
    own docstring calls "human-chosen and guessable by design", with
    `coupon_applied` in the 201 body as a clean hit/miss oracle. Both paths
    now charge one shared per-IP bucket so the cheaper door is not the
    unlocked one.
    """

    @pytest.mark.asyncio
    async def test_a_signup_coupon_is_blocked_once_the_budget_is_spent(
        self, client, auth_headers
    ):
        """Ten redeems exhaust the hourly budget for this IP; the very FIRST
        signup from it must then be refused, even though AUTH_LIMIT is
        untouched. Without a shared bucket this signup is request 1 of 600."""
        for _ in range(10):
            await _redeem(client, auth_headers, ip=_ATTACKER_IP)

        r = await _signup(
            client, "burned@example.com", coupon="GUESS", ip=_ATTACKER_IP
        )
        assert r.status_code == 429, (
            "a coupon attempt through signup ignored the coupon budget: "
            f"{r.status_code} {r.text}"
        )

    @pytest.mark.asyncio
    async def test_a_couponless_signup_is_untouched_by_a_spent_budget(
        self, client, auth_headers
    ):
        """The blast radius must stop at coupon attempts: normal signup keeps
        working exactly as before, at its own AUTH_LIMIT."""
        for _ in range(10):
            await _redeem(client, auth_headers, ip=_ATTACKER_IP)

        r = await _signup(client, "clean@example.com", ip=_ATTACKER_IP)
        assert r.status_code == 201, (
            f"couponless signup was collateral damage: {r.status_code} {r.text}"
        )

    @pytest.mark.asyncio
    async def test_signup_attempts_charge_the_shared_bucket(
        self, client, auth_headers
    ):
        """The other direction: guesses made through signup must deplete the
        budget the dedicated endpoint draws from. Nine signups (kept under
        AUTH_LIMIT's 10/minute, which is exactly why this door was cheaper)
        leave room for one redeem, and the one after it must be refused."""
        for i in range(9):
            r = await _signup(
                client, f"probe{i}@example.com", coupon="GUESS", ip=_ATTACKER_IP
            )
            assert r.status_code == 201, f"signup {i} failed: {r.text}"

        tenth = await _redeem(client, auth_headers, ip=_ATTACKER_IP)
        assert tenth.status_code != 429, "the 10th attempt should still fit"

        eleventh = await _redeem(client, auth_headers, ip=_ATTACKER_IP)
        assert eleventh.status_code == 429, (
            "signup guesses did not deplete the redeem budget: "
            f"{eleventh.status_code}"
        )

    @pytest.mark.asyncio
    async def test_redeem_budget_also_follows_the_family_not_only_the_ip(
        self, client, auth_headers
    ):
        """An IP is rotatable (open proxies, a phone's cell network); the
        family_id in the JWT is not. Redeem is authenticated and parent-only,
        so it charges both dimensions — moving to a fresh IP with the same
        token must not refresh the budget."""
        for _ in range(10):
            await _redeem(client, auth_headers, ip=_ATTACKER_IP)

        r = await _redeem(client, auth_headers, ip="198.51.100.4")
        assert r.status_code == 429, (
            f"rotating the IP refreshed the family's budget: {r.status_code}"
        )
