"""Referral program routes.

Parent-facing "Invita y gana" / "Invite & earn" surface:

- GET /api/referrals/me → this family's referral code, public share link,
  how many families have joined via it, and the reward size in days.

Recording a referral + granting the reward happens in the register-family
flow (app/api/routes/auth.py) when a new family signs up with ?ref=CODE —
not here — so the credit is applied atomically at account creation.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.models import User
from app.services.referral_service import REFERRAL_REWARD_DAYS, ReferralService

router = APIRouter()


class MyReferralResponse(BaseModel):
    code: str
    share_link: str
    joined_count: int
    reward_days: int


@router.get("/me", response_model=MyReferralResponse)
async def get_my_referral(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
):
    """Return the family's referral code + share link + join count.

    Parent-only. Generates the code on first view (idempotent).
    """
    code = await ReferralService.get_or_create_referral_code(
        db, current_user.family_id
    )
    joined_count = await ReferralService.count_successful_referrals(
        db, current_user.family_id
    )
    # Share link points at the PUBLIC frontend origin (email_link_base =
    # PUBLIC_URL, falling back to BASE_URL in local dev), NOT the API origin.
    base = settings.email_link_base.rstrip("/")
    share_link = f"{base}/register?ref={code}" if code else ""
    return MyReferralResponse(
        code=code or "",
        share_link=share_link,
        joined_count=joined_count,
        reward_days=REFERRAL_REWARD_DAYS,
    )
