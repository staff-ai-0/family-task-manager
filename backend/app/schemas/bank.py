"""Family Bank schemas (centavos). See docs/specs/family-bank.md §5."""
from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

_JARS = ("spend", "save", "share")


class KidBankView(BaseModel):
    """Kid bank card. Countdown/preview/automation fields are populated only by
    GET /api/bank/me (null in the parent family list)."""

    user_id: UUID
    name: Optional[str] = None
    spend_cents: int
    save_cents: int
    share_cents: int
    total_cents: int
    allowance_cents: int
    allowance_mode: Optional[str] = None
    payday_weekday: int
    split_spend_pct: int
    split_save_pct: int
    split_share_pct: int
    interest_rate_bps: int
    match_pct: int
    match_cap_cents: int
    save_withdrawal_requires_approval: bool
    next_payday_date: Optional[str] = None
    days_until_payday: Optional[int] = None
    pending_match_cents: Optional[int] = None
    last_payday_at: Optional[datetime] = None
    automation_enabled: Optional[bool] = None


class BankSettingsUpdate(BaseModel):
    """Per-kid config upsert. All fields optional (partial update). When any of
    the three split percentages is supplied, all three must be and sum to 100."""

    allowance_cents: Optional[int] = Field(None, ge=0)
    allowance_mode: Optional[Literal["flat", "chore_proportional", "chore_gated"]] = None
    payday_weekday: Optional[int] = Field(None, ge=0, le=6)
    split_spend_pct: Optional[int] = Field(None, ge=0, le=100)
    split_save_pct: Optional[int] = Field(None, ge=0, le=100)
    split_share_pct: Optional[int] = Field(None, ge=0, le=100)
    interest_rate_bps: Optional[int] = Field(None, ge=0, le=10000)
    match_pct: Optional[int] = Field(None, ge=0, le=200)
    match_cap_cents: Optional[int] = Field(None, ge=0)
    save_withdrawal_requires_approval: Optional[bool] = None

    @model_validator(mode="after")
    def _splits_sum_to_100(self):
        parts = [self.split_spend_pct, self.split_save_pct, self.split_share_pct]
        provided = [p for p in parts if p is not None]
        if provided:
            if len(provided) != 3:
                raise ValueError("All three split percentages must be provided together")
            if sum(p or 0 for p in parts) != 100:
                raise ValueError("Split percentages must sum to 100")
        return self


class ChorePaycheckPreview(BaseModel):
    """Projected weekly chore paycheck — feeds the teen meter + parent review."""

    user_id: UUID
    week_of: date
    mode: str
    cap_cents: int
    done_points: int
    assigned_points: int
    pct: int
    projected_cents: int
    already_released: bool


class ChorePaycheckReleaseBody(BaseModel):
    """Optional parent adjustment (signed cents) added to the computed paycheck —
    a bonus (positive) or dock (negative). Final amount floored at 0."""
    adjustment_cents: int = Field(0, ge=-100000, le=100000)


class ChorePaycheckReleaseResult(BaseModel):
    user_id: UUID
    week_of: date
    done_points: int
    assigned_points: int
    amount_cents: int


class BankTransferRequest(BaseModel):
    user_id: UUID
    from_jar: str
    to_jar: str
    amount_cents: int = Field(..., gt=0)

    @field_validator("from_jar", "to_jar")
    @classmethod
    def _valid_jar(cls, v: str) -> str:
        if v not in _JARS:
            raise ValueError(f"jar must be one of {_JARS}")
        return v


class JarBalances(BaseModel):
    user_id: UUID
    spend_cents: int
    save_cents: int
    share_cents: int
    total_cents: int


class SaveWithdrawalRequest(BaseModel):
    amount_cents: int = Field(..., gt=0)
    reason: Optional[str] = Field(None, max_length=200)


class PayoutRequestBody(BaseModel):
    amount_cents: Optional[int] = Field(None, gt=0)


class BankRequestResponse(BaseModel):
    success: bool
    notified_parents: int
