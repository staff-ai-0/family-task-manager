"""Per-family a2a webhook configuration."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.models import User
from app.schemas.a2a import A2AWebhookRead, A2AWebhookSaveResult, A2AWebhookUpdate
from app.services.budget.a2a_webhook_service import A2AWebhookService

router = APIRouter()


@router.get("", response_model=A2AWebhookRead)
async def get_webhook(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Return current webhook config for the family.  Never exposes the secret."""
    family_id = to_uuid_required(current_user.family_id)
    cfg = await A2AWebhookService.get_config(db, family_id)
    if cfg is None:
        return A2AWebhookRead(enabled=False)
    return cfg


@router.put("", response_model=A2AWebhookSaveResult)
async def put_webhook(
    payload: A2AWebhookUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create or update webhook config.

    When ``rotate_secret=True`` the response includes the new plaintext secret
    (the ONLY time it is returned — store it immediately).  Subsequent reads
    omit the secret entirely.
    """
    family_id = to_uuid_required(current_user.family_id)
    cfg, plaintext = await A2AWebhookService.upsert_config(
        db,
        family_id,
        url=payload.url,
        enabled=payload.enabled,
        rotate_secret=payload.rotate_secret,
    )
    return A2AWebhookSaveResult(
        config=A2AWebhookRead.model_validate(cfg),
        secret=plaintext,
    )
