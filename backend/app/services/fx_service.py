"""Foreign-exchange rate lookup with Redis cache.

Public surface: FXService.get_rate(from_ccy, to_ccy, on_date) -> Decimal | None

Source: https://exchangerate.host (free, no API key). Historical endpoint
returns rates as of a given date. We cache (from, to, date) → rate in Redis
for 24h since historical rates are immutable.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

import httpx
import redis.asyncio as aioredis

from app.core.config import settings


_REDIS_TTL_SECONDS = 24 * 3600

# Module-level singleton. aioredis.from_url() returns a Redis client backed
# by a connection pool — instantiating one per call leaks pools and bloats
# Redis-side connection counts. The pool is lazy-connected on first use.
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    return _redis_client


def _cache_key(from_ccy: str, to_ccy: str, on_date: date) -> str:
    return f"fx:{from_ccy}:{to_ccy}:{on_date.isoformat()}"


class FXService:

    @staticmethod
    async def get_rate(
        from_ccy: str,
        to_ccy: str,
        on_date: date,
    ) -> Optional[Decimal]:
        """Return the rate to convert 1 unit of from_ccy into to_ccy on on_date.

        Returns None on any upstream failure — caller decides fallback.
        """
        from_ccy = from_ccy.upper()
        to_ccy = to_ccy.upper()
        if from_ccy == to_ccy:
            return Decimal("1")

        redis = _get_redis()
        key = _cache_key(from_ccy, to_ccy, on_date)
        try:
            cached = await redis.get(key)
            if cached is not None:
                return Decimal(cached.decode("utf-8"))
        except Exception:
            cached = None

        url = f"https://api.exchangerate.host/{on_date.isoformat()}"
        params = {"base": from_ccy, "symbols": to_ccy}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None

        if not data.get("success", True):  # exchangerate.host omits 'success' on OK
            return None
        rate_val = data.get("rates", {}).get(to_ccy)
        if rate_val is None:
            return None

        rate = Decimal(str(rate_val))
        try:
            await redis.set(key, str(rate), ex=_REDIS_TTL_SECONDS)
        except Exception:
            pass
        return rate
