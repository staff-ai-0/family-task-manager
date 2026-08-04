"""Coupon redemption and credit listing (family-facing).

Mounted under /api/subscriptions alongside the plan/checkout routes — a
coupon is a subscription-adjacent concept from the user's point of view.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.rate_limiter import charge_coupon_attempt
from app.models.user import User
from app.schemas.coupon import (
    CouponSummary,
    CreditResponse,
    RedeemCouponRequest,
)
from app.services.coupon_service import (
    CouponAlreadyRedeemed,
    CouponInvalid,
    CouponService,
)
from app.services.plan_credit_service import PlanCreditService

router = APIRouter()

# One message for every unusable-code reason — see coupon_service's docstring.
_INVALID_DETAIL = {"error": "invalid_or_expired_coupon"}
_ALREADY_REDEEMED_DETAIL = {"error": "already_redeemed"}


@router.post("/coupons/redeem", response_model=CreditResponse)
async def redeem_coupon(
    request: Request,
    payload: RedeemCouponRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
) -> CreditResponse:
    """Redeem a coupon code into a plan credit for the caller's family.

    Charged manually instead of via ``@limiter.limit``: the budget is shared
    with the coupon branch of register-family (a decorator's bucket is scoped
    to one endpoint, which is what let signup guess codes 60x faster), and
    being authenticated here means it can also charge the un-rotatable
    family_id, not only the client IP.
    """
    charge_coupon_attempt(request, family_id=current_user.family_id)
    try:
        coupon, grant = await CouponService.redeem(
            db, family_id=current_user.family_id, code=payload.code
        )
    except CouponAlreadyRedeemed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_ALREADY_REDEEMED_DETAIL,
        ) from None
    except CouponInvalid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_INVALID_DETAIL
        ) from None

    return CreditResponse(
        id=grant.id,
        tier=grant.tier,
        source=grant.source,
        starts_at=grant.starts_at,
        ends_at=grant.ends_at,
        lifetime=grant.ends_at is None,
        coupon=CouponSummary.model_validate(coupon),
    )


@router.get("/credits", response_model=list[CreditResponse])
async def list_credits(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
) -> list[CreditResponse]:
    """Plan credits for the caller's family (drives the UI banner).

    Includes QUEUED grants, not just live ones: under the >=-tier rule a
    second code of the same tier starts when the first ends, and without
    it a successful redemption would leave the page byte-identical — the
    family would retry and get a 409. `starts_at` distinguishes them.
    """
    grants = await PlanCreditService.visible_grants(db, current_user.family_id)
    return [
        CreditResponse(
            id=g.id,
            tier=g.tier,
            source=g.source,
            starts_at=g.starts_at,
            ends_at=g.ends_at,
            lifetime=g.ends_at is None,
            coupon=None,
        )
        for g in grants
    ]
