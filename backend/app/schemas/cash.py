"""Cash currency schemas (centavos)."""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime


class CashSummary(BaseModel):
    user_id: UUID
    name: Optional[str] = None
    current_balance_cents: int
    total_earned_cents: int
    total_paid_cents: int


class CashTxn(BaseModel):
    id: UUID
    type: str
    amount_cents: int
    balance_after: int
    jar: str = "spend"
    description: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PayoutRequest(BaseModel):
    amount_cents: int = Field(..., gt=0)
    # Which jar to debit (Family Bank). Default 'spend'; 'share' settles the
    # Share pledge. Validated against that jar's balance by CashService.
    jar: str = "spend"


class AdjustRequest(BaseModel):
    amount_cents: int
    reason: str = Field(..., min_length=1, max_length=200)


class PayoutResponse(BaseModel):
    success: bool
    new_balance_cents: int
    transaction_id: UUID
