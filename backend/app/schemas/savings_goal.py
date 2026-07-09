"""Kid savings-goal schemas (P2, centavos — CASH ledger / Save jar).

Progress is always computed against the kid's Family Bank **Save jar** balance.
No points fields appear here by design (the goal is cash-only; see
``app/models/kid_savings_goal.py``).
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SavingsGoalCreate(BaseModel):
    """Create a goal. ``user_id`` is required only when a PARENT sets a goal for
    a kid; a kid omits it (creates for themselves, pending approval)."""

    name: str = Field(..., min_length=1, max_length=80)
    target_cents: int = Field(..., gt=0, le=100_000_000)  # cap $1,000,000 MXN
    emoji: Optional[str] = Field(None, max_length=8)
    user_id: Optional[UUID] = None


class SavingsGoalProgress(BaseModel):
    """A goal plus its live progress against the Save jar."""

    id: UUID
    user_id: UUID
    name: str
    emoji: Optional[str] = None
    target_cents: int
    saved_cents: int          # min(save jar, target) — money already earmarked
    save_balance_cents: int   # the kid's full Save jar balance
    remaining_cents: int      # max(0, target - save jar) — "faltan $X"
    progress_pct: int         # 0–100
    reached: bool             # save jar >= target
    status: str               # pending | active | cancelled
    pending_approval: bool    # status == 'pending'
    created_at: datetime

    model_config = {"from_attributes": True}
