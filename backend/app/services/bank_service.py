"""BankService — Family Bank: jar config, jar transfers, kid requests, payday.

Sits on top of ``CashService`` (the low-level jar-aware ledger primitive). This
service owns the higher-level Family Bank surface described in
``docs/specs/family-bank.md``:

- per-kid config upsert (allowance, %-split, interest, match, approval toggle),
- jar transfers (paired net-zero JAR_TRANSFER rows),
- stateless kid requests (save-withdrawal / payout) as localized notifications,
- the hourly payday sweep (match → interest → allowance), timezone-bucketed,
  idempotent per family-local week via ``last_payday_at``.

Hard product constraint: everything here operates ONLY on the CASH ledger. It
never reads or writes ``User.points`` / ``point_transactions``.
"""
import logging
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.family import Family
from app.models.kid_bank import KidBankAccount
from app.models.user import APPROVAL_APPROVED, User, UserRole
from app.services.cash_service import (
    JAR_SAVE,
    JAR_SHARE,
    JAR_SPEND,
    JARS,
    CashService,
    _add_jar,
    _get_account_locked,
    _get_or_create_account_locked,
    _get_user_locked,
    _jar_balance,
)
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def _safe_zoneinfo(tz_name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _fmt_mxn(cents: int) -> str:
    """Format centavos as a peso string, e.g. 12345 → '$123.45'."""
    return f"${cents / 100:,.2f}"


# Config fields a parent may upsert (jar balances are NEVER settable here).
_SETTINGS_FIELDS = (
    "allowance_cents",
    "payday_weekday",
    "split_spend_pct",
    "split_save_pct",
    "split_share_pct",
    "interest_rate_bps",
    "match_pct",
    "match_cap_cents",
    "save_withdrawal_requires_approval",
)


class BankService:
    # ── account access ──────────────────────────────────────────────────────

    @staticmethod
    async def ensure_account(db: AsyncSession, user: User) -> KidBankAccount:
        """Read-or-lazily-create the kid's account (commits on create).

        Seeds ``spend_cents`` from the kid's existing cash so invariant #1 holds
        for pre-existing balances.

        Fast path (account exists) takes no lock. On first-touch we acquire the
        user-row lock FIRST — the same users → kid_bank_accounts order every
        CashService writer uses — before creating the row. Without it this
        non-locking reader (GET /api/bank/me,/family) and a concurrent
        gig-approval/adjust would each issue a plain INSERT of the same
        UNIQUE(user_id) key and deadlock (two speculative inserts waiting on each
        other's transaction). Serializing on the user row makes the second caller
        find the committed row instead; _get_or_create_account_locked still
        guards the residual IntegrityError.
        """
        acct = (
            await db.execute(
                select(KidBankAccount).where(KidBankAccount.user_id == user.id)
            )
        ).scalar_one_or_none()
        if acct is not None:
            return acct
        locked_user = await _get_user_locked(db, user.id)
        acct = await _get_or_create_account_locked(db, locked_user, user.family_id)
        await db.commit()
        await db.refresh(acct)
        return acct

    # ── kid + parent views ────────────────────────────────────────────────

    @staticmethod
    def _next_payday(tz_name: Optional[str], payday_weekday: int):
        """(next_payday_date, days_until) in the family-local timezone."""
        local_now = datetime.now(_safe_zoneinfo(tz_name))
        days = (payday_weekday - local_now.weekday()) % 7
        return (local_now.date() + timedelta(days=days)), days

    @staticmethod
    async def _pending_match(db: AsyncSession, acct: KidBankAccount) -> int:
        base = await BankService._sum_kid_save_deposits(
            db, acct.user_id, acct.last_payday_at
        )
        if not acct.match_pct or base <= 0:
            return 0
        match = base * acct.match_pct // 100
        if acct.match_cap_cents:
            match = min(match, acct.match_cap_cents)
        return match

    @staticmethod
    async def get_kid_bank(db: AsyncSession, user: User) -> dict:
        """Own jars + config + next-payday countdown + pending-match preview."""
        from app.core.premium import get_family_plan_by_id

        acct = await BankService.ensure_account(db, user)
        family = await db.get(Family, user.family_id)
        tz_name = family.timezone if family else "UTC"
        next_date, days_until = BankService._next_payday(tz_name, acct.payday_weekday)
        plan = await get_family_plan_by_id(db, user.family_id)
        return {
            "user_id": user.id,
            "name": user.name,
            "spend_cents": acct.spend_cents,
            "save_cents": acct.save_cents,
            "share_cents": acct.share_cents,
            "total_cents": user.cash_cents,
            "allowance_cents": acct.allowance_cents,
            "payday_weekday": acct.payday_weekday,
            "split_spend_pct": acct.split_spend_pct,
            "split_save_pct": acct.split_save_pct,
            "split_share_pct": acct.split_share_pct,
            "interest_rate_bps": acct.interest_rate_bps,
            "match_pct": acct.match_pct,
            "match_cap_cents": acct.match_cap_cents,
            "save_withdrawal_requires_approval": acct.save_withdrawal_requires_approval,
            "next_payday_date": next_date.isoformat(),
            "days_until_payday": days_until,
            "pending_match_cents": await BankService._pending_match(db, acct),
            "last_payday_at": acct.last_payday_at,
            "automation_enabled": bool(plan.limits.get("family_bank_automation", False)),
        }

    @staticmethod
    async def get_family_bank(db: AsyncSession, parent: User) -> List[dict]:
        """Every kid (TEEN/CHILD) in the parent's family: balances + settings."""
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
            out.append(
                {
                    "user_id": kid.id,
                    "name": kid.name,
                    "spend_cents": acct.spend_cents,
                    "save_cents": acct.save_cents,
                    "share_cents": acct.share_cents,
                    "total_cents": kid.cash_cents,
                    "allowance_cents": acct.allowance_cents,
                    "payday_weekday": acct.payday_weekday,
                    "split_spend_pct": acct.split_spend_pct,
                    "split_save_pct": acct.split_save_pct,
                    "split_share_pct": acct.split_share_pct,
                    "interest_rate_bps": acct.interest_rate_bps,
                    "match_pct": acct.match_pct,
                    "match_cap_cents": acct.match_cap_cents,
                    "save_withdrawal_requires_approval": acct.save_withdrawal_requires_approval,
                    "last_payday_at": acct.last_payday_at,
                }
            )
        return out

    # ── settings upsert ───────────────────────────────────────────────────

    @staticmethod
    async def upsert_settings(
        db: AsyncSession, target_user: User, family_id: UUID, data: dict
    ) -> KidBankAccount:
        """Persist per-kid config. NEVER touches jar balances. Caller (route)
        performs role + tenant checks and the premium gate for automation."""
        user = await _get_user_locked(db, target_user.id)
        acct = await _get_or_create_account_locked(db, user, family_id)
        for field in _SETTINGS_FIELDS:
            if field in data and data[field] is not None:
                setattr(acct, field, data[field])
        await db.commit()
        await db.refresh(acct)
        return acct

    # ── jar transfers ──────────────────────────────────────────────────────

    @staticmethod
    async def execute_transfer(
        db: AsyncSession,
        target_user_id: UUID,
        family_id: UUID,
        from_jar: str,
        to_jar: str,
        amount_cents: int,
        actor_id: UUID,
    ) -> KidBankAccount:
        """Move ``amount_cents`` between two jars as a paired net-zero pair of
        JAR_TRANSFER rows (invariant #3). Total ``cash_cents`` is unchanged, so
        both rows stamp balance_before == balance_after == total.

        ``created_by = actor_id``: a kid's own spend→save transfer is
        kid-initiated and therefore counts toward the parent match; a parent's
        transfer does not (spec §D5). Direction/permission is decided by the
        route; this method enforces jar validity + sufficient balance (422).
        """
        if amount_cents <= 0:
            raise HTTPException(status_code=422, detail="amount_cents must be positive")
        if from_jar not in JARS or to_jar not in JARS or from_jar == to_jar:
            raise HTTPException(status_code=422, detail="invalid jar pair")
        user = await _get_user_locked(db, target_user_id)
        acct = await _get_or_create_account_locked(db, user, family_id)
        if _jar_balance(acct, from_jar) < amount_cents:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "insufficient_jar_balance",
                    "jar": from_jar,
                    "available_cents": _jar_balance(acct, from_jar),
                    "requested_cents": amount_cents,
                },
            )
        total = user.cash_cents
        desc = f"Transfer {from_jar}→{to_jar}"
        db.add_all(
            [
                CashTransaction(
                    type=CashTransactionType.JAR_TRANSFER,
                    user_id=user.id,
                    family_id=family_id,
                    amount_cents=-amount_cents,
                    jar=from_jar,
                    balance_before=total,
                    balance_after=total,
                    created_by=actor_id,
                    description=desc,
                ),
                CashTransaction(
                    type=CashTransactionType.JAR_TRANSFER,
                    user_id=user.id,
                    family_id=family_id,
                    amount_cents=amount_cents,
                    jar=to_jar,
                    balance_before=total,
                    balance_after=total,
                    created_by=actor_id,
                    description=desc,
                ),
            ]
        )
        _add_jar(acct, from_jar, -amount_cents)
        _add_jar(acct, to_jar, amount_cents)
        await db.commit()
        await db.refresh(acct)
        return acct

    # ── stateless kid requests (localized notifications) ────────────────────

    @staticmethod
    async def _notify_parents(
        db: AsyncSession, family_id: UUID, key: str, params: dict
    ) -> int:
        parents = (
            await db.execute(
                select(User).where(
                    User.family_id == family_id,
                    User.role == UserRole.PARENT,
                    User.is_active.is_(True),
                )
            )
        ).scalars().all()
        for parent in parents:
            await NotificationService.create_localized(
                db,
                family_id=family_id,
                user_id=parent.id,
                key=key,
                params=params,
                link="/parent/settings/family-bank",
            )
        return len(parents)

    @staticmethod
    async def request_save_withdrawal(
        db: AsyncSession, kid: User, amount_cents: int, reason: Optional[str] = None
    ) -> int:
        return await BankService._notify_parents(
            db,
            kid.family_id,
            "bank_save_withdrawal_request",
            {"child": kid.name, "amount": _fmt_mxn(amount_cents), "reason": reason or ""},
        )

    @staticmethod
    async def request_payout(
        db: AsyncSession, kid: User, amount_cents: int
    ) -> int:
        return await BankService._notify_parents(
            db,
            kid.family_id,
            "bank_payout_request",
            {"child": kid.name, "amount": _fmt_mxn(amount_cents)},
        )

    # ── payday sweep ────────────────────────────────────────────────────────

    @staticmethod
    async def _sum_kid_save_deposits(
        db: AsyncSession, kid_id: UUID, since: Optional[datetime]
    ) -> int:
        """Sum of KID-INITIATED Save deposits (JAR_TRANSFER credits into save
        with created_by == kid) since ``since``. ``since=None`` (a kid's first
        payday) means all-time — the sweep's WHERE admits last_payday_at IS NULL,
        so the match must not be silently $0 (spec §D5)."""
        q = select(func.coalesce(func.sum(CashTransaction.amount_cents), 0)).where(
            CashTransaction.user_id == kid_id,
            CashTransaction.type == CashTransactionType.JAR_TRANSFER,
            CashTransaction.jar == JAR_SAVE,
            CashTransaction.amount_cents > 0,
            CashTransaction.created_by == kid_id,
        )
        if since is not None:
            q = q.where(CashTransaction.created_at > since)
        return int((await db.execute(q)).scalar() or 0)

    @staticmethod
    async def _pay_one_kid(
        db: AsyncSession, family_id: UUID, user_id: UUID
    ) -> int:
        """One kid's payday in a single transaction. Order: match → interest
        (on post-match, pre-allowance Save) → allowance+split. Returns 1 if a
        notification was sent (money credited), else 0. Lock order: user, acct."""
        user = await _get_user_locked(db, user_id)
        acct = await _get_account_locked(db, user_id)
        if acct is None:
            return 0

        # 1) MATCH on kid-initiated Save deposits since last payday.
        base = await BankService._sum_kid_save_deposits(db, user_id, acct.last_payday_at)
        match = 0
        if acct.match_pct and base > 0:
            match = base * acct.match_pct // 100
            if acct.match_cap_cents:
                match = min(match, acct.match_cap_cents)
        if match > 0:
            CashService.credit_single_jar(
                db, user, acct, family_id, JAR_SAVE, match,
                CashTransactionType.MATCH, description="Aportación de papás",
            )

        # 2) INTEREST on the post-match, pre-allowance Save balance (floor).
        interest = acct.save_cents * acct.interest_rate_bps // 10_000
        if interest > 0:
            CashService.credit_single_jar(
                db, user, acct, family_id, JAR_SAVE, interest,
                CashTransactionType.INTEREST, description="Interés semanal",
            )

        # 3) ALLOWANCE, auto-split (family is already entitled at this point).
        allowance = acct.allowance_cents
        if allowance > 0:
            CashService.credit_split_rows(
                db, user, acct, family_id, allowance,
                CashTransactionType.ALLOWANCE, entitled=True, description="Domingo",
            )

        # Only stamp (and consume the §D5 all-time first-payday match window)
        # when something was actually credited. A no-op payday leaves
        # last_payday_at untouched so a Save deposit made before the parent
        # configures match/interest/allowance is still eligible on the first
        # real payout. The sweep re-evaluates the kid on later ticks (cheap: it
        # already filters to entitled families), so no payout is missed.
        if match or interest or allowance:
            acct.last_payday_at = datetime.now(timezone.utc)
            await db.commit()
            await BankService._notify_payday(
                db, family_id, user_id, allowance, interest, match
            )
            return 1
        # No-op payday: commit any lazily-created account + release locks, but
        # leave last_payday_at untouched so the §D5 all-time match window stays
        # open until the first real payout.
        await db.commit()
        return 0

    @staticmethod
    async def _notify_payday(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        allowance: int,
        interest: int,
        match: int,
    ) -> None:
        total = allowance + interest + match
        if allowance or match:
            key = "payday"
            params = {
                "total": _fmt_mxn(total),
                "allowance": _fmt_mxn(allowance),
                "interest": _fmt_mxn(interest),
                "match": _fmt_mxn(match),
            }
        else:
            key = "payday_interest_only"
            params = {"interest": _fmt_mxn(interest)}
        await NotificationService.create_localized(
            db, family_id=family_id, user_id=user_id, key=key, params=params, link="/bank"
        )

    @staticmethod
    async def run_payday_sweep(db: AsyncSession) -> int:
        """Hourly payday sweep across ALL families, evaluated in family-local
        time. A kid is paid when local weekday == payday_weekday AND local hour
        >= 8 AND last_payday_at < family-local midnight (idempotent per local
        day). Non-entitled families are skipped entirely. Per-kid commit +
        try/except so one bad row never blocks the family. Returns kids paid.
        """
        from app.core.premium import get_family_plan_by_id

        families = (await db.execute(
            select(Family.id, Family.timezone).where(Family.deleted_at.is_(None))
        )).all()
        paid = 0
        for fid, tz_name in families:
            tz = _safe_zoneinfo(tz_name)
            local_now = datetime.now(tz)
            if local_now.hour < 8:  # pay after 08:00 local, not at midnight
                continue

            plan = await get_family_plan_by_id(db, fid)
            if not plan.limits.get("family_bank_automation", False):
                continue

            local_midnight = datetime.combine(local_now.date(), time.min, tzinfo=tz)
            accounts = (
                await db.execute(
                    select(KidBankAccount)
                    .join(User, User.id == KidBankAccount.user_id)
                    .where(
                        KidBankAccount.family_id == fid,
                        KidBankAccount.payday_weekday == local_now.weekday(),
                        or_(
                            KidBankAccount.last_payday_at.is_(None),
                            KidBankAccount.last_payday_at < local_midnight,
                        ),
                        User.is_active.is_(True),
                        User.approval_status == APPROVAL_APPROVED,
                    )
                )
            ).scalars().all()

            for acct in accounts:
                try:
                    paid += await BankService._pay_one_kid(db, fid, acct.user_id)
                except Exception:
                    await db.rollback()
                    logger.exception("payday failed for kid %s", acct.user_id)
        return paid
