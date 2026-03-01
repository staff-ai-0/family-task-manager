"""Test that deprecated sync endpoints return 410 Gone status."""
import pytest
from httpx import AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_sync_health_returns_410():
    """Test sync/health endpoint returns 410 Gone."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/sync/health")
        assert response.status_code == 410
        data = response.json()
        assert "detail" in data


@pytest.mark.asyncio
async def test_sync_status_returns_410():
    """Test sync/status endpoint returns 410 Gone."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/sync/status?family_id=test-id")
        assert response.status_code == 410


@pytest.mark.asyncio
async def test_sync_trigger_returns_410():
    """Test sync/trigger endpoint returns 410 Gone."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post("/api/sync/trigger", json={"family_id": "test-id"})
        assert response.status_code == 410
