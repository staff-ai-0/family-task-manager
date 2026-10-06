"""Bank-transfer receipts → recorded chore paychecks.

The scanner (payout_receipt_scanner_service) only reads the slip. Here the
parent-facing proposal is built deterministically (kid, weeks, split) and, on
confirm, the receipt amount — the real money that left the account — becomes
the paycheck: each week goes through BankService.release_chore_paycheck with
``adjustment = amount − computed base`` so points_rate conversion, the kid
notification and per-(kid, week) idempotency all stay in their one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.payout_receipt import PayoutReceipt
from app.models.user import User
from app.services.bank_service import CHORE_PAYCHECK_MODES, BankService
from app.services.payout_receipt_scanner_service import week_numbers_from_concept

MAX_WEEKS = 8


@dataclass
class WeekProposal:
    week_of: date
    amount_cents: int
    already_paid: bool = False
    projected_cents: int = 0


@dataclass
class ReceiptProposal:
    allocations: list[WeekProposal] = field(default_factory=list)
    weeks_from_concept: bool = False
    mismatch: bool = False


def iso_week_monday(week: int, receipt_date: date) -> Optional[date]:
    """Monday of ISO week ``week`` in the receipt's year; a slip dated early
    January that names week 52 means the PREVIOUS year's."""
    for year in (receipt_date.year, receipt_date.year - 1, receipt_date.year + 1):
        try:
            monday = date.fromisocalendar(year, week, 1)
        except ValueError:
            continue
        if abs((monday - receipt_date).days) <= 60:
            return monday
    return None


def split_amount(total_cents: int, n: int) -> list[int]:
    """Even split in whole centavos; the remainder rides on the last week."""
    base = total_cents // n
    parts = [base] * n
    parts[-1] += total_cents - base * n
    return parts


async def released_weeks(db: AsyncSession, family_id: UUID, user_id: UUID) -> set[date]:
    rows = await db.execute(
        select(CashTransaction.week_of).where(
            CashTransaction.user_id == user_id,
            CashTransaction.family_id == family_id,
            CashTransaction.type == CashTransactionType.ALLOWANCE,
            CashTransaction.week_of.is_not(None),
        ).distinct()
    )
    return {r[0] for r in rows.all()}


async def propose(
    db: AsyncSession, kid: User, family_id: UUID, *, amount_cents: int,
    concept: str, receipt_date: Optional[date],
) -> ReceiptProposal:
    """Which week(s) a transfer pays, and how the amount splits across them.
    Weeks named in the concept win; otherwise the oldest unpaid weeks, as many
    as the amount covers at the kid's weekly cap. The parent can edit all of it."""
    paid = await released_weeks(db, family_id, kid.id)
    today = await BankService._family_local_today(db, family_id)
    this_monday = BankService._week_monday(today)

    mondays: list[date] = []
    if receipt_date:
        for n in week_numbers_from_concept(concept):
            monday = iso_week_monday(n, receipt_date)
            if monday and monday <= this_monday and monday not in mondays:
                mondays.append(monday)
    from_concept = bool(mondays)

    if not mondays:
        outstanding = await BankService.list_outstanding_weeks(db, kid, family_id)
        unpaid = [w["week_of"] for w in outstanding if not w.get("already_released")]
        acct = await BankService.ensure_account(db, kid)
        cap = int(acct.allowance_cents or 0)
        wanted = max(1, round(amount_cents / cap)) if cap > 0 else 1
        mondays = unpaid[:wanted] or [this_monday]
    mondays = sorted(mondays)[:MAX_WEEKS]

    parts = split_amount(amount_cents, len(mondays))
    allocations = []
    projected_total = 0
    for monday, part in zip(mondays, parts):
        preview = await BankService.chore_paycheck_preview(db, kid, family_id, monday)
        projected_total += preview["projected_cents"]
        allocations.append(WeekProposal(
            week_of=monday, amount_cents=part,
            already_paid=monday in paid, projected_cents=preview["projected_cents"],
        ))
    return ReceiptProposal(
        allocations=allocations,
        weeks_from_concept=from_concept,
        mismatch=projected_total != amount_cents,
    )


async def folio_exists(db: AsyncSession, family_id: UUID, folio: str) -> bool:
    return (await db.execute(
        select(PayoutReceipt.id).where(
            PayoutReceipt.family_id == family_id, PayoutReceipt.folio == folio,
        ).limit(1)
    )).scalar_one_or_none() is not None


async def record_receipt(
    db: AsyncSession, kid: User, family_id: UUID, *, folio: str, receipt_date: Optional[date],
    concept: str, amount_cents: int, allocations: list[dict], released_by: UUID,
) -> dict:
    """Record ONE receipt. ``allocations`` = [{week_of, amount_cents}]; their sum
    must equal the receipt. Everything is validated before the first write — the
    per-week releases commit as they go, so a late failure would leave a half-paid
    receipt. A week already paid is topped up with its share; an unpaid one is
    released so that the kid is credited exactly the share."""
    if not allocations or len(allocations) > MAX_WEEKS:
        raise HTTPException(status_code=422, detail=f"allocate between 1 and {MAX_WEEKS} weeks")
    if sum(int(a["amount_cents"]) for a in allocations) != amount_cents:
        raise HTTPException(status_code=422, detail="week amounts must add up to the receipt amount")
    acct = await BankService.ensure_account(db, kid)
    if acct.allowance_mode not in CHORE_PAYCHECK_MODES:
        raise HTTPException(status_code=422, detail="kid is not on a chore-based allowance")
    if await folio_exists(db, family_id, folio):
        raise HTTPException(status_code=409, detail="this receipt (folio) was already recorded")

    this_monday = BankService._week_monday(await BankService._family_local_today(db, family_id))
    paid = await released_weeks(db, family_id, kid.id)
    plan: list[tuple[date, int, bool]] = []
    seen: set[date] = set()
    for a in allocations:
        monday = BankService._week_monday(a["week_of"])
        share = int(a["amount_cents"])
        if monday in seen:
            raise HTTPException(status_code=422, detail="a week appears twice")
        seen.add(monday)
        if monday > this_monday:
            raise HTTPException(status_code=422, detail="week_of cannot be in the future")
        if share < 0:
            raise HTTPException(status_code=422, detail="week amounts cannot be negative")
        is_top_up = monday in paid
        if is_top_up and share == 0:
            raise HTTPException(status_code=422, detail="a week that is already paid needs a positive amount")
        plan.append((monday, share, is_top_up))

    receipt = PayoutReceipt(
        family_id=family_id, user_id=kid.id, folio=folio, receipt_date=receipt_date,
        amount_cents=amount_cents, concept=concept or None, created_by=released_by,
        weeks=[{"week_of": m.isoformat(), "amount_cents": s, "top_up": t} for m, s, t in plan],
    )
    db.add(receipt)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="this receipt (folio) was already recorded")

    results = []
    for monday, share, is_top_up in plan:
        if is_top_up:
            res = await BankService.release_chore_paycheck(
                db, kid, family_id, monday, entitled=True, adjustment_cents=share,
                released_by=released_by, top_up=True,
            )
        else:
            base = (await BankService.chore_paycheck_preview(db, kid, family_id, monday))["projected_cents"]
            res = await BankService.release_chore_paycheck(
                db, kid, family_id, monday, entitled=True, adjustment_cents=share - base,
                released_by=released_by, reference=folio,
            )
        results.append({"week_of": monday, "amount_cents": share, "top_up": is_top_up,
                        "points_converted": res.get("points_converted", 0)})
    return {"folio": folio, "user_id": kid.id, "amount_cents": amount_cents, "weeks": results}


def match_beneficiary(beneficiary: str, members: list) -> Optional[UUID]:
    """The kid a slip's "Nombre del beneficiario" means. Bank names are the
    account holder's FULL legal name ("Ariana Michelle M") while the family
    member is usually just "Ariana", so — unlike name_match.match_members — the
    MEMBER's name must be a token-prefix of the beneficiary. Two members that
    fit (Ana / Ana Sofia) → the longer, more specific one wins only if it alone
    fits; a true tie matches nobody. Never guess between kids."""
    from app.services.name_match import fold

    target = fold(beneficiary).split()
    if not target:
        return None
    fits = []
    for m in members:
        name = fold(m.name).split()
        if name and target[: len(name)] == name:
            fits.append((len(name), m.id))
    if not fits:
        return None
    top = max(n for n, _ in fits)
    best = [i for n, i in fits if n == top]
    return best[0] if len(best) == 1 else None
