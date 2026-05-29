"""Internal retry sweep — invoked by external cron / scheduler."""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services.budget.a2a_webhook_service import A2AWebhookService


router = APIRouter()


def _require_token(x_internal_token: str = Header(None)):
    # Constant-time comparison so an attacker can't time-side-channel the
    # token byte by byte. Reject empty/missing on either side first to
    # avoid passing None into compare_digest (which would TypeError).
    expected = settings.INTERNAL_API_TOKEN or ""
    if (
        not expected
        or not x_internal_token
        or not hmac.compare_digest(x_internal_token, expected)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid internal token")


@router.post("/a2a/retry")
async def retry_sweep(
    _t: None = Depends(_require_token),
    db: AsyncSession = Depends(get_db),
):
    n = await A2AWebhookService.sweep_retries(db, limit=50)
    return {"processed": n}
