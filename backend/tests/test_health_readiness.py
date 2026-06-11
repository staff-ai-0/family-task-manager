"""B3: /health must not falsely claim DB connectivity; /ready does the real check.

Before: GET /health returned {"database": "connected"} from a static dict without
ever touching the database. Now /health is a cheap liveness probe (no dependency
claims) and /ready actually pings the DB (+ Redis), returning 503 when degraded.
"""
import pytest
from httpx import AsyncClient


class TestHealthReadiness:
    @pytest.mark.asyncio
    async def test_health_is_liveness_only(self, client: AsyncClient):
        r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        # It must no longer falsely assert DB status without checking.
        assert "database" not in body

    @pytest.mark.asyncio
    async def test_ready_actually_checks_database(self, client: AsyncClient):
        r = await client.get("/ready")
        # DB + Redis are up in the test environment → ready.
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["database"] == "connected"

    @pytest.mark.asyncio
    async def test_ready_returns_503_when_db_down(self, client: AsyncClient, monkeypatch):
        """If the DB check raises, readiness must report 503 (not a cheerful 200)."""
        import app.main as main_mod

        class _BoomSession:
            async def __aenter__(self):
                raise RuntimeError("db down")

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr(main_mod, "AsyncSessionLocal", lambda: _BoomSession())
        r = await client.get("/ready")
        assert r.status_code == 503
        assert r.json()["database"] == "error"
