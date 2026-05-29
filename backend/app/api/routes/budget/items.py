"""Item history + price-trend endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.premium import require_feature
from app.core.type_utils import to_uuid_required
from app.models import User
from app.schemas.budget import ItemTrend, TransactionItemRead
from app.services.budget.transaction_item_service import TransactionItemService

router = APIRouter()


@router.get("/", response_model=list[TransactionItemRead])
async def list_items(
    normalized_name: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List transaction items for the authenticated user's family.

    Optionally filter by normalized_name, since (datetime), with pagination.
    Family-scoped — results are always isolated to the calling user's family.
    """
    family_id = to_uuid_required(current_user.family_id)
    return await TransactionItemService.list_for_family(
        db,
        family_id,
        normalized_name=normalized_name,
        since=since,
        limit=limit,
        offset=offset,
    )


@router.get("/trend", response_model=Optional[ItemTrend])
async def get_trend(
    normalized_name: str = Query(...),
    window_days: int = Query(90, ge=7, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return price-trend data for an item over the last window_days.

    Returns null (HTTP 200) when there are fewer than 3 samples with
    unit_price_cents — the caller should treat null as "no trend data".
    """
    family_id = to_uuid_required(current_user.family_id)
    # Item-trend lookup is a Pro feature; the scanner pipeline already
    # checks this with is_feature_enabled(), but the public endpoint also
    # needs the gate so direct API callers can't bypass plan limits.
    await require_feature("item_trends", db, current_user)
    return await TransactionItemService.get_trend(
        db,
        family_id,
        normalized_name=normalized_name,
        window_days=window_days,
    )
