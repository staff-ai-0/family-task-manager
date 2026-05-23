"""Web Push subscription endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.push_service import PushService

router = APIRouter()


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(..., min_length=1, max_length=255)
    auth: str = Field(..., min_length=1, max_length=255)


class PushSubscribeRequest(BaseModel):
    endpoint: str = Field(..., min_length=1, max_length=2048)
    keys: PushSubscriptionKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(..., min_length=1, max_length=2048)


@router.get("/public-key")
async def get_vapid_public_key():
    """Public VAPID key for the browser PushManager.subscribe() call."""
    if not settings.VAPID_PUBLIC_KEY:
        raise HTTPException(
            status_code=503,
            detail="Web Push is not configured on this server",
        )
    return {"public_key": settings.VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def subscribe(
    body: PushSubscribeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a browser push endpoint for the current user."""
    sub = await PushService.subscribe(
        db,
        user_id=to_uuid_required(current_user.id),
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
    )
    return {"id": str(sub.id), "endpoint": sub.endpoint}


@router.post("/unsubscribe")
async def unsubscribe(
    body: PushUnsubscribeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    removed = await PushService.unsubscribe(
        db,
        user_id=to_uuid_required(current_user.id),
        endpoint=body.endpoint,
    )
    return {"removed": removed}
