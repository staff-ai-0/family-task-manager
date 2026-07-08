"""CashService — cash currency ledger (centavos). Gigs credit; parents pay out.

Symmetric with PointsService but a separate balance (User.cash_cents) and
ledger (cash_transactions). Cash never converts to/from points. See
docs/superpowers/specs/2026-06-30-two-currency-economy-design.md.

Family Bank (P1, docs/specs/family-bank.md): every cash mutation is now
jar-aware. Each kid has a ``kid_bank_accounts`` row holding three materialized
jar balances (spend/save/share) plus parent config. This service owns the
low-level ledger primitives — credit-split, jar-cascade debit, single-jar
credit — and enforces the hard invariant:

    spend_cents + save_cents + share_cents == users.cash_cents  (always)

Lock order is ALWAYS: users row first (``_get_user_locked``,
populate_existing=True) THEN the kid_bank_accounts row (``_get_account_locked``).
Never the reverse (deadlock). ``BankService`` builds the higher-level jar
config / transfers / payday sweep on top of these primitives.
"""
from uuid import UUID
from typing import Optional, List

from sqlalchemy import select, and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.kid_bank import KidBankAccount
from app.models.user import User
from app.core.exceptions import ValidationException
from app.services.base_service import get_user_by_id


# Jar names and the deterministic cascade / emit order (spend → save → share).
JAR_SPEND = "spend"
JAR_SAVE = "save"
JAR_SHARE = "share"
JARS = (JAR_SPEND, JAR_SAVE, JAR_SHARE)


async def _get_user_locked(db: AsyncSession, user_id: UUID) -> User:
    """Fetch a user row with FOR UPDATE so concurrent cash mutations on the same
    balance serialize (no lost updates, no negative balance from a payout race).

    populate_existing=True is required: callers (cash routes, gig_claim_service)
    pre-load the User into this session before locking, so without it SQLAlchemy
    returns the cached instance with STALE attributes and the lock is defeated.
    """
    return (
        await db.execute(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _get_account_locked(
    db: AsyncSession, user_id: UUID
) -> Optional[KidBankAccount]:
    """Lock an existing kid_bank_accounts row FOR UPDATE (None if absent).

    MUST be called AFTER _get_user_locked so the lock order is users →
    kid_bank_accounts. populate_existing so a pre-loaded account isn't stale.
    """
    return (
        await db.execute(
            select(KidBankAccount)
            .where(KidBankAccount.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _get_or_create_account_locked(
    db: AsyncSession, user: User, family_id: UUID
) -> KidBankAccount:
    """Lock (or lazily create) the kid's bank account row. Call AFTER
    _get_user_locked (lock order: users → kid_bank_accounts).

    A freshly created row seeds ``spend_cents = user.cash_cents`` so invariant #1
    (spend+save+share == cash_cents) holds for pre-existing / legacy balances —
    all historical cash was spendable, mirroring the ledger's jar='spend'
    server_default backfill.

    The user-row lock serializes concurrent *locked* creators, but a FOR UPDATE
    select over a non-existent row takes no lock, so a non-locking reader
    (BankService.ensure_account on GET /me or /family) can insert the same row
    between our miss and flush. Handle that with an IntegrityError re-select on
    the UNIQUE(user_id) constraint via a SAVEPOINT so the outer transaction is
    not aborted.
    """
    acct = await _get_account_locked(db, user.id)
    if acct is None:
        acct = KidBankAccount(
            user_id=user.id,
            family_id=family_id,
            spend_cents=user.cash_cents,
            save_cents=0,
            share_cents=0,
        )
        db.add(acct)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            # A concurrent creator won; re-select and lock the winning row.
            acct = await _get_account_locked(db, user.id)
    return acct


def _jar_balance(acct: KidBankAccount, jar: str) -> int:
    return getattr(acct, f"{jar}_cents")


def _add_jar(acct: KidBankAccount, jar: str, delta: int) -> None:
    setattr(acct, f"{jar}_cents", getattr(acct, f"{jar}_cents") + delta)


def _split_shares(amount_cents: int, acct: KidBankAccount) -> dict:
    """Divide a positive credit across jars per the kid's config.

    Floor each non-spend share; the remainder goes to ``spend`` (documented
    rounding, integer centavos). Sum of shares == amount_cents exactly.
    """
    save_amt = amount_cents * acct.split_save_pct // 100
    share_amt = amount_cents * acct.split_share_pct // 100
    spend_amt = amount_cents - save_amt - share_amt  # remainder → spend
    return {JAR_SPEND: spend_amt, JAR_SAVE: save_amt, JAR_SHARE: share_amt}


class CashService:
    """Service for cash-related operations (centavos)."""

    # ── plan entitlement (credit-time gating) ───────────────────────────────

    @staticmethod
    async def _bank_automation_entitled(db: AsyncSession, family_id: UUID) -> bool:
        """True when the family's plan grants ``family_bank_automation``.

        Consulted at CREDIT time (gig approval / allowance) so a non-entitled
        family falls back to a 100/0/0 split regardless of stored config — the
        payday sweep never touches the gig-approval path, so a sweep-side check
        alone cannot enforce the split gating (spec §10).
        """
        from app.core.premium import get_family_plan_by_id

        plan = await get_family_plan_by_id(db, family_id)
        return bool(plan.limits.get("family_bank_automation", False))

    # ── low-level ledger primitives (no commit) ─────────────────────────────

    @staticmethod
    def credit_single_jar(
        db: AsyncSession,
        user: User,
        acct: KidBankAccount,
        family_id: UUID,
        jar: str,
        amount_cents: int,
        tx_type: CashTransactionType,
        *,
        description: Optional[str] = None,
        created_by: Optional[UUID] = None,
    ) -> CashTransaction:
        """Credit a positive ``amount_cents`` into a single jar (one ledger row).

        Used by INTEREST / MATCH (always ``save``). balance_before/after stamp
        the TOTAL. Caller updates ``last_payday_at`` and commits.
        """
        before = user.cash_cents
        tx = CashTransaction(
            type=tx_type,
            user_id=user.id,
            family_id=family_id,
            amount_cents=amount_cents,
            jar=jar,
            balance_before=before,
            balance_after=before + amount_cents,
            created_by=created_by,
            description=description,
        )
        _add_jar(acct, jar, amount_cents)
        user.cash_cents = before + amount_cents
        db.add(tx)
        return tx

    @staticmethod
    def credit_split_rows(
        db: AsyncSession,
        user: User,
        acct: KidBankAccount,
        family_id: UUID,
        amount_cents: int,
        tx_type: CashTransactionType,
        *,
        entitled: bool,
        assignment_id: Optional[UUID] = None,
        gig_claim_id: Optional[UUID] = None,
        created_by: Optional[UUID] = None,
        description: Optional[str] = None,
    ) -> List[CashTransaction]:
        """Split a positive credit across jars, emitting one ledger row per
        non-zero jar with a contiguous balance chain against the TOTAL.

        When ``entitled`` is False the split collapses to 100/0/0 (single
        jar='spend' row) — credit-time premium gating (spec §D2/§10). A zero
        credit still emits a single jar='spend' row so a gig always leaves a
        ledger entry (preserves pre-Family-Bank behaviour).
        """
        if entitled and amount_cents > 0:
            shares = _split_shares(amount_cents, acct)
        else:
            shares = {JAR_SPEND: amount_cents, JAR_SAVE: 0, JAR_SHARE: 0}

        emit = [(jar, shares[jar]) for jar in JARS if shares[jar] > 0]
        if not emit:  # zero (or all-zero) credit — keep a single ledger entry
            emit = [(JAR_SPEND, 0)]

        rows: List[CashTransaction] = []
        running = user.cash_cents
        for jar, share in emit:
            tx = CashTransaction(
                type=tx_type,
                user_id=user.id,
                family_id=family_id,
                assignment_id=assignment_id,
                gig_claim_id=gig_claim_id,
                created_by=created_by,
                amount_cents=share,
                jar=jar,
                balance_before=running,
                balance_after=running + share,
                description=description,
            )
            running += share
            _add_jar(acct, jar, share)
            db.add(tx)
            rows.append(tx)
        user.cash_cents = running
        return rows

    @staticmethod
    def debit_cascade_rows(
        db: AsyncSession,
        user: User,
        acct: KidBankAccount,
        family_id: UUID,
        magnitude: int,
        tx_type: CashTransactionType,
        *,
        created_by: Optional[UUID] = None,
        description: Optional[str] = None,
        assignment_id: Optional[UUID] = None,
        gig_claim_id: Optional[UUID] = None,
    ) -> List[CashTransaction]:
        """Debit ``magnitude`` (>0) from the total, cascading spend→save→share so
        no jar goes negative. THE shared debit helper for every signed debit
        against the total (GIG_EARNED claw-back AND negative ADJUSTMENT).

        The applied debit is floored at the total (``min(magnitude, total)``): a
        debit exceeding the total pays out the whole balance and lands at 0,
        preserving the existing /api/cash adjust floor-at-zero contract. Because
        sum(jars) == total (invariant #1), the cascade can always cover the
        floored amount without any jar going negative. Emits one negative ledger
        row per jar touched (contiguous balance chain); a debit against a zero
        balance emits a single zero jar='spend' row.
        """
        applied = min(magnitude, user.cash_cents)
        rows: List[CashTransaction] = []
        running = user.cash_cents
        remaining = applied
        for jar in JARS:  # spend → save → share
            if remaining <= 0:
                break
            take = min(_jar_balance(acct, jar), remaining)
            if take <= 0:
                continue
            tx = CashTransaction(
                type=tx_type,
                user_id=user.id,
                family_id=family_id,
                assignment_id=assignment_id,
                gig_claim_id=gig_claim_id,
                created_by=created_by,
                amount_cents=-take,
                jar=jar,
                balance_before=running,
                balance_after=running - take,
                description=description,
            )
            running -= take
            _add_jar(acct, jar, -take)
            db.add(tx)
            rows.append(tx)
            remaining -= take
        user.cash_cents = running
        if not rows:  # magnitude > 0 but total == 0 — keep a ledger entry
            tx = CashTransaction(
                type=tx_type,
                user_id=user.id,
                family_id=family_id,
                assignment_id=assignment_id,
                gig_claim_id=gig_claim_id,
                created_by=created_by,
                amount_cents=0,
                jar=JAR_SPEND,
                balance_before=running,
                balance_after=running,
                description=description,
            )
            db.add(tx)
            rows.append(tx)
        return rows

    # ── public API ──────────────────────────────────────────────────────────

    @staticmethod
    async def get_balance(db: AsyncSession, user_id: UUID) -> int:
        user = await get_user_by_id(db, user_id)
        return user.cash_cents

    @staticmethod
    async def award_gig_cash(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        assignment_id: Optional[UUID],
        amount_cents: int,
        description: Optional[str] = None,
        gig_claim_id: Optional[UUID] = None,
    ) -> CashTransaction:
        """Credit (or claw back, if negative) gig-board cash. Caller commits.

        Mirrors PointsService.award_gig_points: no commit, so it composes inside
        the gig-approval transaction. A positive credit is auto-split per the
        kid's jar config (100/0/0 when the family lacks family_bank_automation);
        a negative amount cascades spend→save→share via the shared debit helper.
        Returns the last ledger row (its balance_after is the new total). Call
        sites in gig_claim_service ignore the return value.
        """
        user = await _get_user_locked(db, user_id)
        acct = await _get_or_create_account_locked(db, user, family_id)
        desc = description or f"Gig — ${amount_cents / 100:.2f} MXN"
        if amount_cents >= 0:
            entitled = await CashService._bank_automation_entitled(db, family_id)
            rows = CashService.credit_split_rows(
                db, user, acct, family_id, amount_cents,
                CashTransactionType.GIG_EARNED,
                entitled=entitled,
                assignment_id=assignment_id,
                gig_claim_id=gig_claim_id,
                description=desc,
            )
        else:
            rows = CashService.debit_cascade_rows(
                db, user, acct, family_id, -amount_cents,
                CashTransactionType.GIG_EARNED,
                assignment_id=assignment_id,
                gig_claim_id=gig_claim_id,
                description=desc,
            )
        return rows[-1]

    @staticmethod
    async def record_payout(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        amount_cents: int,
        created_by: UUID,
        jar: str = JAR_SPEND,
    ) -> CashTransaction:
        """Parent records a payout (full or partial) against a jar. Debits that
        jar + the total. Default jar='spend'; jar='share' settles the Share
        pledge. Validates against the JAR balance, not just the total.
        """
        if amount_cents <= 0:
            raise ValidationException("Payout amount must be positive")
        if jar not in JARS:
            raise ValidationException(f"Invalid jar '{jar}'")
        user = await _get_user_locked(db, user_id)
        acct = await _get_or_create_account_locked(db, user, family_id)
        jar_bal = _jar_balance(acct, jar)
        if amount_cents > jar_bal:
            raise ValidationException(
                f"Payout exceeds {jar} balance. {jar.capitalize()} "
                f"${jar_bal / 100:.2f}, requested ${amount_cents / 100:.2f}"
            )
        before = user.cash_cents
        tx = CashTransaction(
            type=CashTransactionType.PAYOUT,
            user_id=user_id,
            family_id=family_id,
            amount_cents=-amount_cents,
            jar=jar,
            balance_before=before,
            balance_after=before - amount_cents,
            created_by=created_by,
            description=f"Paid ${amount_cents / 100:.2f} MXN",
        )
        _add_jar(acct, jar, -amount_cents)
        user.cash_cents = before - amount_cents
        db.add(tx)
        await db.commit()
        await db.refresh(tx)
        return tx

    @staticmethod
    async def adjust(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        amount_cents: int,
        reason: str,
        created_by: UUID,
    ) -> CashTransaction:
        """Manual signed cash adjustment by a parent. Floors balance at 0.

        Positive → credited to ``spend`` (single row, v1). Negative → cascades
        spend→save→share via the shared debit helper (a debit can exceed the
        spend jar), so invariant #1 holds and ck_kid_bank_ranges never trips.
        The floor-at-zero-total contract of /api/cash/{id}/adjust is unchanged.
        """
        user = await _get_user_locked(db, user_id)
        acct = await _get_or_create_account_locked(db, user, family_id)
        if amount_cents >= 0:
            before = user.cash_cents
            tx = CashTransaction(
                type=CashTransactionType.ADJUSTMENT,
                user_id=user_id,
                family_id=family_id,
                amount_cents=amount_cents,
                jar=JAR_SPEND,
                balance_before=before,
                balance_after=before + amount_cents,
                created_by=created_by,
                description=reason,
            )
            _add_jar(acct, JAR_SPEND, amount_cents)
            user.cash_cents = before + amount_cents
            db.add(tx)
        else:
            rows = CashService.debit_cascade_rows(
                db, user, acct, family_id, -amount_cents,
                CashTransactionType.ADJUSTMENT,
                created_by=created_by,
                description=reason,
            )
            tx = rows[-1]
        await db.commit()
        await db.refresh(tx)
        return tx

    @staticmethod
    async def get_history(
        db: AsyncSession, user_id: UUID, limit: int = 50
    ) -> List[CashTransaction]:
        q = (
            select(CashTransaction)
            .where(CashTransaction.user_id == user_id)
            .order_by(CashTransaction.created_at.desc())
            .limit(limit)
        )
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def get_summary(db: AsyncSession, user_id: UUID) -> dict:
        user = await get_user_by_id(db, user_id)
        earned = (
            await db.execute(
                select(func.coalesce(func.sum(CashTransaction.amount_cents), 0)).where(
                    and_(
                        CashTransaction.user_id == user_id,
                        CashTransaction.amount_cents > 0,
                    )
                )
            )
        ).scalar() or 0
        # Count ALL outflows (payouts + negative adjustments), not just PAYOUT
        # rows, so that earned - paid == current_balance reconciles exactly.
        paid = (
            await db.execute(
                select(func.coalesce(func.sum(CashTransaction.amount_cents), 0)).where(
                    and_(
                        CashTransaction.user_id == user_id,
                        CashTransaction.amount_cents < 0,
                    )
                )
            )
        ).scalar() or 0
        return {
            "current_balance": int(user.cash_cents),
            "total_earned": int(earned),
            "total_paid": int(abs(paid)),
        }
