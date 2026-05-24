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


@router.get("/health")
async def push_health(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Diagnostic for parents — confirms VAPID keys are present and
    the user has subscriptions on file. Returns booleans + counts."""
    from sqlalchemy import func, select
    from app.models.push_subscription import PushSubscription

    pub = settings.VAPID_PUBLIC_KEY or ""
    priv = settings.VAPID_PRIVATE_KEY or ""
    configured = bool(pub and priv)
    # Sanity: VAPID public key in raw form is 65 bytes → 87 base64url chars.
    # Private key in PEM is multi-line ~200 chars. Allow some slack.
    valid_keys = configured and len(pub) >= 80 and len(priv) >= 60

    sub_count = int((await db.execute(
        select(func.count()).select_from(PushSubscription).where(
            PushSubscription.user_id == to_uuid_required(current_user.id)
        )
    )).scalar() or 0)

    return {
        "configured": configured,
        "valid_keys": valid_keys,
        "claim_email": settings.VAPID_CLAIM_EMAIL,
        "subscription_count": sub_count,
        "public_key_length": len(pub),
        "private_key_length": len(priv),
    }


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
