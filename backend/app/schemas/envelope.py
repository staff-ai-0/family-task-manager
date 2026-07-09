"""Kid budget-envelope schemas (P2 — CASH ledger / Family Bank jars).

A *thin, read-only projection* that presents each kid's existing Family Bank
jars (Spend / Save / Share, ES: Gastar / Ahorrar / Compartir) as budget
"envelopes", plus the optional named savings goal (``kid_savings_goals``) as a
target overlay on the Save envelope. There is NO new table behind this — every
value is derived from ``kid_bank_accounts`` (jar balances = ``users.cash_cents``)
and the kid's open goal.

Hard product constraint: this is the CASH ledger only. Envelopes track cash /
jars and NEVER points — no ``users.points`` / ``point_transactions`` field
appears here by design (chores → points; only /gigs → cash).
"""
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class EnvelopeGoal(BaseModel):
    """The kid's named savings goal, projected onto the Save envelope. Live
    progress is measured against the Save-jar balance (see SavingsGoalService)."""

    id: UUID
    name: str
    emoji: Optional[str] = None
    target_cents: int
    saved_cents: int          # min(save jar, target) — money already earmarked
    remaining_cents: int      # max(0, target - save jar) — "faltan $X"
    progress_pct: int         # 0–100 toward target
    reached: bool             # save jar >= target
    pending_approval: bool    # goal.status == 'pending'


class Envelope(BaseModel):
    """One budget envelope = one Family Bank jar. ``pct_of_total`` is the jar's
    share of the kid's total cash (the card's progress bar). ``goal`` is only
    populated on the ``save`` envelope, and only when the kid has an open goal."""

    key: str                  # "spend" | "save" | "share"
    balance_cents: int
    pct_of_total: int         # 0–100, this jar's share of total cash
    goal: Optional[EnvelopeGoal] = None


class KidEnvelopesView(BaseModel):
    """A kid's envelopes = the three jars + total cash. ``total_cents`` equals
    ``users.cash_cents`` by Family Bank invariant #1 (jar sum == cash)."""

    user_id: UUID
    name: Optional[str] = None
    total_cents: int
    envelopes: List[Envelope]
