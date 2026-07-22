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
    allowance_mode: Optional[
        Literal["flat", "chore_proportional", "chore_gated", "points_rate"]
    ] = None
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
    discounted_pct: int
    projected_cents: int
    already_released: bool


class PayoutTaskDetail(BaseModel):
    """One week-task behind a chore-paycheck row (payouts dashboard tooltip).
    Status buckets mirror the paycheck credit math: only `credited` rows earn."""

    title: str
    points: int
    earned_points: int
    status: Literal["credited", "pending_review", "missed", "not_done"]
    grade: Optional[str] = None
    partial_credit_pct: Optional[int] = None
    assigned_date: date
    completed_at: Optional[datetime] = None
    approval_notes: Optional[str] = None


class PayoutPaycheckWeek(BaseModel):
    """One chore-paycheck week for a kid — either a fully-elapsed unreleased
    week, or the current week (in progress, or already released — the
    current week always appears regardless of release status so the
    dashboard never loses track of it). Same per-task shape as history."""

    week_of: date
    amount_cents: int
    done_points: int
    assigned_points: int
    pct: int
    is_current_week: bool
    already_released: bool
    tasks: list[PayoutTaskDetail] = []


class PayoutSummaryKid(BaseModel):
    user_id: UUID
    name: str
    cash_pending_cents: int
    paycheck_cents: int
    paycheck_released: bool
    allowance_mode: str
    # Week progress behind paycheck_cents (0 on flat mode).
    done_points: int = 0
    assigned_points: int = 0
    pct: int = 0
    # Per-task breakdown of the week (empty on flat mode).
    tasks: list[PayoutTaskDetail] = []
    # Every unreleased week (past + current), oldest first — empty on flat mode.
    outstanding_weeks: list[PayoutPaycheckWeek] = []


class PayoutSummary(BaseModel):
    """Everything a parent currently owes the kids: gig cash awaiting payout
    plus chore paychecks awaiting release. paycheck_total_cents/grand_total_cents
    stay current-week-only (unchanged); outstanding_*_total_cents sum across
    every outstanding week including past ones — the honest "what do I owe
    right now" figure the payouts dashboard should show."""

    kids: list[PayoutSummaryKid]
    cash_total_cents: int
    paycheck_total_cents: int
    grand_total_cents: int
    outstanding_paycheck_total_cents: int
    outstanding_grand_total_cents: int


class PayoutWeekHistory(BaseModel):
    """One past released chore-paycheck week — amount, when, and why
    (same per-task breakdown shape as PayoutSummaryKid.tasks)."""

    week_of: date
    amount_cents: int
    released_at: datetime
    tasks: list[PayoutTaskDetail]


class PayoutHistoryResponse(BaseModel):
    weeks: list[PayoutWeekHistory]
    has_more: bool


class ChorePaycheckOutstandingResponse(BaseModel):
    weeks: list[PayoutPaycheckWeek]


class ChorePaycheckReleaseBody(BaseModel):
    """Optional parent adjustment (signed cents) added to the computed paycheck —
    a bonus (positive) or dock (negative). Final amount floored at 0. week_of
    targets a specific week (any date in it; normalized to that week's Monday
    server-side) — omit to release the current week, unchanged default."""
    adjustment_cents: int = Field(0, ge=-100000, le=100000)
    week_of: Optional[date] = None


class ChorePaycheckReleaseResult(BaseModel):
    user_id: UUID
    week_of: date
    done_points: int
    assigned_points: int
    amount_cents: int
    # points_rate mode only: points deducted because they were paid out as cash.
    points_converted: int = 0


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
