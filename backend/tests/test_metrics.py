"""Tests for the hand-rolled Prometheus /metrics endpoint.

Covers the two things ops cares about:
  1. It's access-guarded (fail-closed token check; 403 when unauth/unconfigured).
  2. When authorized it returns 200 text/plain in Prometheus exposition format
     with the expected metric names, and the in-process LLM counter is wired.

The gauge COUNT queries run against the app's own AsyncSessionLocal (same
pattern as /ready), so these tests assert on the exposition *shape* and on the
deterministic in-process counter rather than on DB-fixture counts.
"""
import re

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.config import settings

TOKEN = "test-internal-secret"


@pytest_asyncio.fixture(autouse=True)
async def _dispose_app_engine():
    """Dispose the module-global app engine's pool after each test.

    The /metrics route (like /ready) opens sessions on the shared
    ``app.core.database.AsyncSessionLocal`` rather than the test-overridden
    ``get_db``. pytest-asyncio gives each test function its own event loop, so a
    pooled asyncpg connection opened here would otherwise linger bound to this
    (soon-closed) loop and break the NEXT file's ``pool_pre_ping``. Disposing the
    pool after each test keeps the shared engine clean for later tests.
    """
    yield
    from app.core.database import engine

    await engine.dispose()

EXPECTED_METRICS = [
    "family_up",
    "family_metrics_db_up",
    "family_families_total",
    "family_active_users",
    "family_nonfree_subscriptions",
    "family_pending_receipt_drafts",
    "family_overdue_assignments",
    "family_llm_calls_total",
]


@pytest.fixture
def configured_token(monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", TOKEN)
    return TOKEN


class TestMetricsGuard:
    @pytest.mark.asyncio
    async def test_unconfigured_token_rejects_even_with_header(
        self, client: AsyncClient, monkeypatch
    ):
        """Fail-closed: if INTERNAL_API_TOKEN is unset, nothing gets in."""
        monkeypatch.setattr(settings, "INTERNAL_API_TOKEN", "")
        r = await client.get("/metrics", headers={"X-Internal-Token": "anything"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_no_token_is_rejected(self, client: AsyncClient, configured_token):
        r = await client.get("/metrics")
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_wrong_token_is_rejected(self, client: AsyncClient, configured_token):
        r = await client.get("/metrics", headers={"X-Internal-Token": "nope"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_wrong_bearer_is_rejected(self, client: AsyncClient, configured_token):
        r = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 403


class TestMetricsContent:
    @pytest.mark.asyncio
    async def test_x_internal_token_grants_access(
        self, client: AsyncClient, configured_token
    ):
        r = await client.get("/metrics", headers={"X-Internal-Token": TOKEN})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")

    @pytest.mark.asyncio
    async def test_bearer_token_grants_access(
        self, client: AsyncClient, configured_token
    ):
        r = await client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")

    @pytest.mark.asyncio
    async def test_all_expected_metric_names_present(
        self, client: AsyncClient, configured_token
    ):
        r = await client.get("/metrics", headers={"X-Internal-Token": TOKEN})
        assert r.status_code == 200
        body = r.text
        for name in EXPECTED_METRICS:
            assert f"# TYPE {name} " in body, f"missing TYPE line for {name}"
            assert f"# HELP {name} " in body, f"missing HELP line for {name}"
            # A value line: "<name> <number>"
            assert re.search(rf"^{re.escape(name)} \d", body, re.MULTILINE), (
                f"missing value line for {name}"
            )

    @pytest.mark.asyncio
    async def test_family_up_is_one(self, client: AsyncClient, configured_token):
        r = await client.get("/metrics", headers={"X-Internal-Token": TOKEN})
        assert "family_up 1" in r.text


class TestLlmCounter:
    @pytest.mark.asyncio
    async def test_llm_counter_reflects_record_llm_call(
        self, client: AsyncClient, configured_token
    ):
        """record_llm_call() bumps must show up in the scraped counter value."""
        from app.core.metrics import record_llm_call, snapshot

        before = snapshot().get("llm_calls_total", 0)
        for _ in range(3):
            record_llm_call()

        r = await client.get("/metrics", headers={"X-Internal-Token": TOKEN})
        assert r.status_code == 200
        m = re.search(r"^family_llm_calls_total (\d+)", r.text, re.MULTILINE)
        assert m is not None
        assert int(m.group(1)) >= before + 3
