"""Operator coupon catalog. Superadmin only; see admin/__init__.py."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_superadmin
from app.models.user import User
from app.schemas.coupon import (
    CouponAdminResponse,
    CreateCouponRequest,
    UpdateCouponRequest,
)
from app.services.admin.admin_coupon_service import AdminCouponService

router = APIRouter()


class RevokeCreditRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


@router.get("/coupons", response_model=list[CouponAdminResponse])
async def list_coupons(
    is_active: Optional[bool] = Query(None),
    kind: Optional[str] = Query(None),
    campaign: Optional[str] = Query(None),
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminCouponService.list_coupons(
        db, is_active=is_active, kind=kind, campaign=campaign
    )


@router.post(
    "/coupons",
    response_model=CouponAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_coupon(
    payload: CreateCouponRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminCouponService.create(db, operator=operator, payload=payload)


@router.patch("/coupons/{coupon_id}", response_model=CouponAdminResponse)
async def update_coupon(
    coupon_id: UUID,
    payload: UpdateCouponRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Amend the reversible fields. code/kind/tier/duration_days are
    immutable — UpdateCouponRequest simply does not carry them."""
    return await AdminCouponService.update(
        db, operator=operator, coupon_id=coupon_id, payload=payload
    )


@router.get("/coupons/{coupon_id}/redemptions")
async def coupon_redemptions(
    coupon_id: UUID,
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await AdminCouponService.redemptions(db, coupon_id=coupon_id)


@router.post("/credits/{grant_id}/revoke")
async def revoke_credit(
    grant_id: UUID,
    payload: RevokeCreditRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await AdminCouponService.revoke_grant(
        db, operator=operator, grant_id=grant_id, reason=payload.reason
    )
