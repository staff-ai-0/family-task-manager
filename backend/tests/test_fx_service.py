"""FXService — historical rate lookup via exchangerate.host with Redis cache."""

import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.fx_service import FXService


@pytest.mark.asyncio
async def test_returns_one_for_same_currency():
    rate = await FXService.get_rate("MXN", "MXN", date(2026, 5, 28))
    assert rate == Decimal("1")


@pytest.mark.asyncio
async def test_fetches_and_caches(monkeypatch):
    """First call hits HTTP; second hits Redis cache."""
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(side_effect=[None, b"17.15"])
    fake_redis.set = AsyncMock()
    monkeypatch.setattr("app.services.fx_service._get_redis",
                        lambda: fake_redis)

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "success": True,
        "rates": {"MXN": 17.15},
    }
    fake_response.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_response)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch("app.services.fx_service.httpx.AsyncClient", return_value=fake_client):
        rate = await FXService.get_rate("USD", "MXN", date(2026, 5, 28))
        assert rate == Decimal("17.15")
        fake_redis.set.assert_awaited_once()

        # Second call: redis returns cached
        rate2 = await FXService.get_rate("USD", "MXN", date(2026, 5, 28))
        assert rate2 == Decimal("17.15")


@pytest.mark.asyncio
async def test_returns_none_on_http_failure(monkeypatch):
    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=None)
    fake_redis.set = AsyncMock()
    monkeypatch.setattr("app.services.fx_service._get_redis",
                        lambda: fake_redis)

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(side_effect=RuntimeError("boom"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch("app.services.fx_service.httpx.AsyncClient", return_value=fake_client):
        rate = await FXService.get_rate("USD", "MXN", date(2026, 5, 28))
        assert rate is None
