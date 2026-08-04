from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RedeemCouponRequest(BaseModel):
    # Length matches coupons.code; the service normalizes case and trims.
    code: str = Field(..., min_length=1, max_length=32)


class CouponSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    kind: str
    campaign: Optional[str] = None


class CreditResponse(BaseModel):
    """One active credit window, family-facing."""

    id: UUID
    tier: str
    source: str
    starts_at: datetime
    ends_at: Optional[datetime] = None
    lifetime: bool
    coupon: Optional[CouponSummary] = None


class CouponAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    kind: str
    tier: str
    duration_days: Optional[int] = None
    max_redemptions: Optional[int] = None
    redemption_count: int
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    is_active: bool
    campaign: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class CreateCouponRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{3,31}$")
    kind: str = Field(..., pattern=r"^(launch|beta|comp)$")
    tier: str = Field(..., pattern=r"^(plus|pro)$")
    # None => lifetime. Capped at 5 years so a typo cannot comp for a century.
    duration_days: Optional[int] = Field(None, ge=1, le=1825)
    max_redemptions: Optional[int] = Field(None, ge=1)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    campaign: Optional[str] = Field(None, max_length=120)
    notes: Optional[str] = Field(None, max_length=500)


class UpdateCouponRequest(BaseModel):
    """Only the reversible fields. code, kind, tier and duration_days are
    immutable once created: changing them would retroactively alter what
    already-issued grants meant."""

    is_active: Optional[bool] = None
    valid_until: Optional[datetime] = None
    max_redemptions: Optional[int] = Field(None, ge=1)
    notes: Optional[str] = Field(None, max_length=500)
