"""B1: auth endpoints must be rate limited (brute-force / enumeration defense).

Before: no endpoint had any rate limit. A burst of login attempts from one client
must start returning 429 once the per-window limit is exceeded.
"""
import pytest

from app.core.rate_limiter import limiter


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
