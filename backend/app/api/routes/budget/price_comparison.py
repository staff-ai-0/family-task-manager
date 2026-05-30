"""Server-side proxy to the price-checker agent's read endpoint.

Signs the outbound request with the family's webhook secret. The secret
stays in the FastAPI process — Astro and the browser never see it.
"""

import hashlib
import hmac
import logging
import os
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.budget.a2a_webhook_service import A2AWebhookService

router = APIRouter()
logger = logging.getLogger(__name__)

PRICE_CHECKER_URL = os.environ.get(
    "PRICE_CHECKER_URL", "https://price-checker.agent-ia.mx"
)
TIMEOUT_SECONDS = 10.0


@router.get("/{transaction_id}")
async def get_comparison(
    transaction_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    cfg = await A2AWebhookService.get_config(db, family_id)
    if cfg is None or not cfg.enabled:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "no a2a webhook configured for this family",
        )

    tx_str = str(transaction_id)
    sig = "sha256=" + hmac.new(
        cfg.secret.encode("utf-8"), tx_str.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    url = f"{PRICE_CHECKER_URL}/v1/receipts/{tx_str}/comparisons"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers={
                "X-A2A-Family": str(family_id),
                "X-A2A-Signature": sig,
            })
    except httpx.HTTPError as exc:
        logger.warning("price-checker unreachable: %s", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "price-checker temporarily unreachable",
        )

    if resp.status_code == 404:
        raise HTTPException(404, "no comparisons yet")
    if resp.status_code >= 400:
        logger.warning("price-checker returned %d: %s",
                       resp.status_code, resp.text[:200])
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "price-checker upstream error",
        )
    return resp.json()
