"""SavingsGoalService (P2) — a kid's named CASH savings goal (Save jar).

Sits beside the Family Bank. Everything here is measured against the kid's
**Save-jar** balance (``kid_bank_accounts.save_cents``) — the CASH currency. It
never reads or writes ``users.points`` / ``point_transactions``: the savings goal
is deliberately decoupled from the points economy (hard product constraint —
chores→points, gigs→cash). The points-based reward goal is a separate feature
(``RewardGoalService`` / ``UserRewardGoal``).

Flows:
- A PARENT sets a goal for a kid → created ``active`` (approved on the spot).
- A KID proposes a goal for themselves → created ``pending`` until a parent
  approves it (``approve_goal``).
- Either can ``cancel_goal`` (terminal). v1 allows at most ONE pending-or-active
  goal per kid (re-checked here + backed by a partial unique index).

"Reached" is derived from the Save-jar balance, never a stored status. When an
*active* goal's Save balance first crosses ``target_cents`` the service stamps
``reached_at`` and fires a one-time celebration notification (idempotent).
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kid_bank import KidBankAccount
from app.models.kid_savings_goal import (
    GOAL_ACTIVE,
    GOAL_CANCELLED,
    GOAL_OPEN_STATUSES,
    GOAL_PENDING,
    KidSavingsGoal,
)
from app.models.user import User, UserRole
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def _fmt_mxn(cents: int) -> str:
    return f"${cents / 100:,.2f}"


class SavingsGoalService:
    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _save_balance(db: AsyncSession, user_id: UUID) -> int:
        """The kid's Save-jar balance in centavos (0 if no bank account yet).

        Read-only: never lazily creates the account, so a plain progress read
        has no side effects."""
        val = (
            await db.execute(
                select(KidBankAccount.save_cents).where(
                    KidBankAccount.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        return int(val or 0)

    @staticmethod
    def _progress(goal: KidSavingsGoal, save_cents: int) -> dict:
        target = int(goal.target_cents)
        saved = min(save_cents, target)
        remaining = max(0, target - save_cents)
        pct = min(100, round(save_cents / target * 100)) if target > 0 else 100
        return {
            "id": goal.id,
            "user_id": goal.user_id,
            "name": goal.name,
            "emoji": goal.emoji,
            "target_cents": target,
            "saved_cents": saved,
            "save_balance_cents": int(save_cents),
            "remaining_cents": remaining,
            "progress_pct": int(pct),
            "reached": save_cents >= target,
            "status": goal.status,
            "pending_approval": goal.status == GOAL_PENDING,
            "created_at": goal.created_at,
        }

    @staticmethod
    async def _open_goal_row(
        db: AsyncSession, user_id: UUID
    ) -> Optional[KidSavingsGoal]:
        return (
            await db.execute(
                select(KidSavingsGoal).where(
                    KidSavingsGoal.user_id == user_id,
                    KidSavingsGoal.status.in_(GOAL_OPEN_STATUSES),
                )
            )
        ).scalar_one_or_none()

    # ── celebration (one-time, idempotent) ──────────────────────────────────

    @staticmethod
    async def _maybe_celebrate(
        db: AsyncSession, goal: KidSavingsGoal, save_cents: int
    ) -> bool:
        """Fire the 'goal reached' notification exactly once when an ACTIVE
        goal's Save balance first crosses target. Guarded by reached_at.

        Returns True if it fired (and committed). Never raises — a notification
        failure must not break the read."""
        if goal.status != GOAL_ACTIVE or goal.reached_at is not None:
            return False
        if save_cents < goal.target_cents:
            return False
        goal.reached_at = datetime.now(timezone.utc)
        try:
            await NotificationService.create_localized(
                db,
                family_id=goal.family_id,
                user_id=goal.user_id,
                key="savings_goal_reached_kid",
                params={"goal": goal.name, "amount": _fmt_mxn(goal.target_cents)},
                link="/bank",
                push=True,
            )
            kid = await db.get(User, goal.user_id)
            kid_name = kid.name if kid else "Kid"
            parents = (
                await db.scalars(
                    select(User).where(
                        User.family_id == goal.family_id,
                        User.role == UserRole.PARENT,
                        User.is_active.is_(True),
                    )
                )
            ).all()
            for parent in parents:
                await NotificationService.create_localized(
                    db,
                    family_id=goal.family_id,
                    user_id=parent.id,
                    key="savings_goal_reached_parent",
                    params={
                        "kid": kid_name,
                        "goal": goal.name,
                        "amount": _fmt_mxn(goal.target_cents),
                    },
                    link="/parent/settings/family-bank",
                    push=True,
                    lang=getattr(parent, "preferred_lang", None) or "es",
                )
        except Exception:
            logger.warning("savings goal celebrate: notification failed", exc_info=True)
        await db.commit()
        await db.refresh(goal)
        return True

    # ── reads ────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_active(
        db: AsyncSession, kid: User, notify: bool = True
    ) -> Optional[dict]:
        """The kid's own open (pending/active) goal + live progress, or None.

        When ``notify`` and the active goal is freshly reached, fires the
        one-time celebration."""
        goal = await SavingsGoalService._open_goal_row(db, kid.id)
        if goal is None:
            return None
        save_cents = await SavingsGoalService._save_balance(db, kid.id)
        if notify:
            await SavingsGoalService._maybe_celebrate(db, goal, save_cents)
        return SavingsGoalService._progress(goal, save_cents)

    @staticmethod
    async def get_family(db: AsyncSession, parent: User) -> List[dict]:
        """Every kid's open goal in the parent's family (list of progress dicts).

        Read-only (does not fire celebrations — that happens on the kid's own
        read / bank page)."""
        rows = (
            await db.execute(
                select(KidSavingsGoal)
                .where(
                    KidSavingsGoal.family_id == parent.family_id,
                    KidSavingsGoal.status.in_(GOAL_OPEN_STATUSES),
                )
            )
        ).scalars().all()
        out: List[dict] = []
        for goal in rows:
            save_cents = await SavingsGoalService._save_balance(db, goal.user_id)
            out.append(SavingsGoalService._progress(goal, save_cents))
        return out

    # ── writes ───────────────────────────────────────────────────────────────

    @staticmethod
    async def create_goal(
        db: AsyncSession,
        actor: User,
        *,
        kid: User,
        name: str,
        target_cents: int,
        emoji: Optional[str] = None,
    ) -> dict:
        """Create a goal for ``kid``. Parent-actor → active; kid-actor → pending.

        Caller (route) has already verified ``kid`` is a CHILD/TEEN in the
        actor's family and, for a kid-actor, that ``kid`` is the actor. Rejects
        a second open goal (409)."""
        if await SavingsGoalService._open_goal_row(db, kid.id) is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "goal_exists",
                    "message": "This kid already has an active savings goal.",
                },
            )
        is_parent = actor.role == UserRole.PARENT
        goal = KidSavingsGoal(
            family_id=kid.family_id,
            user_id=kid.id,
            name=name.strip(),
            emoji=(emoji.strip() if emoji else None) or None,
            target_cents=target_cents,
            status=GOAL_ACTIVE if is_parent else GOAL_PENDING,
            created_by=actor.id,
            approved_by=actor.id if is_parent else None,
        )
        db.add(goal)
        try:
            await db.commit()
        except IntegrityError:
            # Lost a race on the partial-unique index — another open goal exists.
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "goal_exists",
                    "message": "This kid already has an active savings goal.",
                },
            )
        await db.refresh(goal)
        if not is_parent:
            await SavingsGoalService._notify_parents_new_goal(db, goal)
        save_cents = await SavingsGoalService._save_balance(db, kid.id)
        return SavingsGoalService._progress(goal, save_cents)

    @staticmethod
    async def _notify_parents_new_goal(
        db: AsyncSession, goal: KidSavingsGoal
    ) -> None:
        try:
            kid = await db.get(User, goal.user_id)
            kid_name = kid.name if kid else "Kid"
            parents = (
                await db.scalars(
                    select(User).where(
                        User.family_id == goal.family_id,
                        User.role == UserRole.PARENT,
                        User.is_active.is_(True),
                    )
                )
            ).all()
            for parent in parents:
                await NotificationService.create_localized(
                    db,
                    family_id=goal.family_id,
                    user_id=parent.id,
                    key="savings_goal_request_parent",
                    params={
                        "kid": kid_name,
                        "goal": goal.name,
                        "amount": _fmt_mxn(goal.target_cents),
                    },
                    link="/parent/settings/family-bank",
                    push=True,
                    lang=getattr(parent, "preferred_lang", None) or "es",
                )
        except Exception:
            logger.warning("savings goal request: notification failed", exc_info=True)

    @staticmethod
    async def _get_in_family(
        db: AsyncSession, goal_id: UUID, family_id: UUID
    ) -> KidSavingsGoal:
        goal = (
            await db.execute(
                select(KidSavingsGoal).where(
                    KidSavingsGoal.id == goal_id,
                    KidSavingsGoal.family_id == family_id,
                )
            )
        ).scalar_one_or_none()
        if goal is None:
            raise HTTPException(status_code=404, detail="Goal not found")
        return goal

    @staticmethod
    async def approve_goal(
        db: AsyncSession, parent: User, goal_id: UUID
    ) -> dict:
        """Parent approves a kid's pending goal (pending → active)."""
        goal = await SavingsGoalService._get_in_family(db, goal_id, parent.family_id)
        if goal.status == GOAL_ACTIVE:
            save_cents = await SavingsGoalService._save_balance(db, goal.user_id)
            return SavingsGoalService._progress(goal, save_cents)
        if goal.status != GOAL_PENDING:
            raise HTTPException(
                status_code=409, detail="Only a pending goal can be approved"
            )
        goal.status = GOAL_ACTIVE
        goal.approved_by = parent.id
        await db.commit()
        await db.refresh(goal)
        try:
            await NotificationService.create_localized(
                db,
                family_id=goal.family_id,
                user_id=goal.user_id,
                key="savings_goal_approved_kid",
                params={"goal": goal.name},
                link="/bank",
                push=True,
            )
        except Exception:
            logger.warning("savings goal approve: notification failed", exc_info=True)
        save_cents = await SavingsGoalService._save_balance(db, goal.user_id)
        # Approving can instantly reach the goal (money already in Save).
        await SavingsGoalService._maybe_celebrate(db, goal, save_cents)
        return SavingsGoalService._progress(goal, save_cents)

    @staticmethod
    async def cancel_goal(db: AsyncSession, actor: User, goal_id: UUID) -> None:
        """Cancel (terminal) a goal. A kid may cancel only their own goal; a
        parent may cancel any kid's goal in the family."""
        goal = await SavingsGoalService._get_in_family(db, goal_id, actor.family_id)
        if actor.role != UserRole.PARENT and goal.user_id != actor.id:
            raise HTTPException(
                status_code=403, detail="You can only cancel your own goal"
            )
        if goal.status in GOAL_OPEN_STATUSES:
            goal.status = GOAL_CANCELLED
            await db.commit()
