"""Internal retry sweep — invoked by external cron / scheduler."""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services.budget.a2a_webhook_service import A2AWebhookService


router = APIRouter()


def _require_token(x_internal_token: str = Header(None)):
    if not settings.INTERNAL_API_TOKEN or x_internal_token != settings.INTERNAL_API_TOKEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid internal token")


@router.post("/a2a/retry")
async def retry_sweep(
    _t: None = Depends(_require_token),
    db: AsyncSession = Depends(get_db),
):
    n = await A2AWebhookService.sweep_retries(db, limit=50)
    return {"processed": n}
