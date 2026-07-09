"""EnvelopeService — kid budget-envelopes as a THIN projection (P2, CASH only).

Presents each kid's existing Family Bank jars (Spend / Save / Share) as budget
"envelopes" fed by chores/gigs cash, plus their optional named savings goal
(``kid_savings_goals``) overlaid on the Save envelope. This closes the
budget-benchmark gap "no one gives kids their own envelopes fed by chores/gigs"
WITHOUT a new table: every number is derived from ``kid_bank_accounts`` (via
``BankService``) and the open goal (via ``SavingsGoalService``).

Hard product constraint (two-currency economy): this reads ONLY the CASH ledger
(``kid_bank_accounts`` jar balances == ``users.cash_cents``). It never reads,
writes, or converts ``users.points`` / ``point_transactions``.

Reads are side-effect-light: ``BankService.ensure_account`` may lazily create a
kid's default (no-op) bank row on first touch — exactly as the deployed
``GET /api/bank/me`` and ``/family`` already do — and the goal read is
``notify=False`` so the projection never fires the "goal reached" celebration
(that stays owned by ``GET /api/bank/goals/me``).
"""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kid_bank import KidBankAccount
from app.models.user import User, UserRole
from app.services.bank_service import BankService
from app.services.savings_goal_service import SavingsGoalService

# The three fixed jars, in display order (spec §D1).
JAR_KEYS = ("spend", "save", "share")


class EnvelopeService:
    # ── projection ───────────────────────────────────────────────────────────

    @staticmethod
    def _project(kid: User, acct: KidBankAccount, goal: Optional[dict]) -> dict:
        """Build the envelopes view for one kid from their jar balances + goal.

        ``total_cents`` is the jar sum, which equals ``users.cash_cents`` by
        Family Bank invariant #1. ``pct_of_total`` is each jar's share of that
        total (per-envelope rounding; informational progress bar, not a ledger
        figure). The named savings goal (if any) is attached to the ``save``
        envelope only, since it is tracked against the Save jar.
        """
        balances = {
            "spend": acct.spend_cents,
            "save": acct.save_cents,
            "share": acct.share_cents,
        }
        total = balances["spend"] + balances["save"] + balances["share"]

        def pct(bal: int) -> int:
            return int(round(bal * 100 / total)) if total > 0 else 0

        envelopes: List[dict] = []
        for key in JAR_KEYS:
            bal = balances[key]
            env = {
                "key": key,
                "balance_cents": bal,
                "pct_of_total": pct(bal),
                "goal": None,
            }
            if key == "save" and goal is not None:
                env["goal"] = {
                    "id": goal["id"],
                    "name": goal["name"],
                    "emoji": goal.get("emoji"),
                    "target_cents": goal["target_cents"],
                    "saved_cents": goal["saved_cents"],
                    "remaining_cents": goal["remaining_cents"],
                    "progress_pct": goal["progress_pct"],
                    "reached": goal["reached"],
                    "pending_approval": goal["pending_approval"],
                }
            envelopes.append(env)

        return {
            "user_id": kid.id,
            "name": kid.name,
            "total_cents": total,
            "envelopes": envelopes,
        }

    # ── reads ────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_kid_envelopes(db: AsyncSession, kid: User) -> dict:
        """One kid's envelopes: their three jars + open savings goal overlay.

        Caller (route) has already resolved + authorized ``kid`` (own kid, or a
        parent's in-family kid). Read-only w.r.t. the goal (no celebration)."""
        acct = await BankService.ensure_account(db, kid)
        goal = await SavingsGoalService.get_active(db, kid, notify=False)
        return EnvelopeService._project(kid, acct, goal)

    @staticmethod
    async def get_family_envelopes(db: AsyncSession, parent: User) -> List[dict]:
        """Every kid (CHILD/TEEN) in the parent's family, envelopes per kid.

        Family-scoped: only members sharing ``parent.family_id`` are returned."""
        kids = (
            await db.execute(
                select(User).where(
                    User.family_id == parent.family_id,
                    User.role.in_([UserRole.CHILD, UserRole.TEEN]),
                )
            )
        ).scalars().all()
        out: List[dict] = []
        for kid in kids:
            acct = await BankService.ensure_account(db, kid)
            goal = await SavingsGoalService.get_active(db, kid, notify=False)
            out.append(EnvelopeService._project(kid, acct, goal))
        return out
