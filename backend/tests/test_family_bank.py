"""Family Bank (P1-W1) tests — spec §11.

Groups: settings CRUD + validation, lazy account creation, %-split application,
negative-debit cascade (shared helper), jar transfers, payout-by-jar, payday
(allowance / interest / match / idempotency / timezone / first-payday NULL),
premium gating (credit-time + settings-time), notifications, two-currency guard,
and family isolation.

Run: podman exec -e PYTHONPATH=/app family_app_backend \
     pytest tests/test_family_bank.py -v --no-cov
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.family import Family
from app.models.kid_bank import KidBankAccount
from app.models.point_transaction import PointTransaction
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.user import APPROVAL_APPROVED, APPROVAL_PENDING, User, UserRole
from app.services.bank_service import BankService
from app.services.cash_service import CashService
from sqlalchemy import func, select


# ── helpers ──────────────────────────────────────────────────────────────────


async def _mk_family(db, tz="UTC"):
    fam = Family(name="Fam", timezone=tz)
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


async def _mk_kid(db, fam, cash=0, role=UserRole.CHILD, approval=APPROVAL_APPROVED,
                  active=True, lang="es"):
    u = User(
        email=f"k{uuid4().hex[:10]}@t.com", name="Kiddo", role=role,
        family_id=fam.id, email_verified=True, cash_cents=cash, points=0,
        approval_status=approval, is_active=active, preferred_lang=lang,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _mk_parent(db, fam):
    return await _mk_kid(db, fam, role=UserRole.PARENT)


async def _entitle_plus(db, fam):
    """Give the family an active Plus plan with family_bank_automation=True.

    Idempotent on the (name, currency) unique row so several families in one
    test can share the single Plus plan."""
    plan = (await db.execute(
        select(SubscriptionPlan).where(
            SubscriptionPlan.name == "plus", SubscriptionPlan.currency == "USD"
        )
    )).scalar_one_or_none()
    if plan is None:
        plan = SubscriptionPlan(
            name="plus", display_name="Plus", display_name_es="Plus",
            currency="USD", price_monthly_cents=9900, price_annual_cents=99000,
            limits={"family_bank_automation": True, "max_family_members": 8}, sort_order=1,
        )
        db.add(plan)
        await db.commit()
        await db.refresh(plan)
    now = datetime.now(timezone.utc)
    sub = FamilySubscription(
        family_id=fam.id, plan_id=plan.id, billing_cycle="monthly", status="active",
        current_period_start=now, current_period_end=now + timedelta(days=30),
    )
    db.add(sub)
    await db.commit()
    return plan


async def _set_config(db, kid, **kwargs):
    """Directly set config on the kid's (lazily created) account, bypassing the
    route's premium gate — used to exercise service behaviour on any plan."""
    acct = await BankService.ensure_account(db, kid)
    for k, v in kwargs.items():
        setattr(acct, k, v)
    await db.commit()
    await db.refresh(acct)
    return acct


async def _rows(db, user_id, tx_type=None):
    q = select(CashTransaction).where(CashTransaction.user_id == user_id)
    if tx_type is not None:
        q = q.where(CashTransaction.type == tx_type)
    return list((await db.execute(q.order_by(CashTransaction.created_at))).scalars().all())


async def _assert_invariant(db, user_id):
    user = await db.get(User, user_id)
    acct = (await db.execute(
        select(KidBankAccount).where(KidBankAccount.user_id == user_id)
    )).scalar_one()
    assert acct.spend_cents + acct.save_cents + acct.share_cents == user.cash_cents, (
        f"invariant broken: {acct.spend_cents}+{acct.save_cents}+{acct.share_cents} "
        f"!= {user.cash_cents}"
    )
    assert acct.spend_cents >= 0 and acct.save_cents >= 0 and acct.share_cents >= 0


def _tz_daytime():
    """Pick an IANA zone where it is currently daytime (local hour in [9,21]) so
    payday-sweep tests are deterministic regardless of wall-clock run time."""
    now = datetime.now(timezone.utc)
    for name in (
        "Pacific/Kiritimati", "Pacific/Auckland", "Asia/Tokyo", "Asia/Kolkata",
        "Europe/Madrid", "UTC", "America/Mexico_City", "America/Los_Angeles",
        "Pacific/Honolulu", "Pacific/Pago_Pago",
    ):
        local = now.astimezone(ZoneInfo(name))
        if 9 <= local.hour <= 21:
            return name, local.weekday()
    return "UTC", now.weekday()


# ── 1. Lazy account creation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lazy_account_seeds_spend_from_cash(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=7000)
    acct = await BankService.ensure_account(db, kid)
    # No-op config defaults + spend seeded from pre-existing cash (invariant).
    assert (acct.split_spend_pct, acct.split_save_pct, acct.split_share_pct) == (100, 0, 0)
    assert acct.allowance_cents == 0 and acct.interest_rate_bps == 0 and acct.match_pct == 0
    assert acct.payday_weekday == 6
    assert acct.spend_cents == 7000 and acct.save_cents == 0 and acct.share_cents == 0
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_unconfigured_credit_is_single_spend_row(db):
    """Default 100/0/0 → today's exact behaviour: one row, jar='spend'."""
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=0)
    await CashService.award_gig_cash(db, kid.id, fam.id, None, 5000, "gig")
    await db.commit()
    rows = await _rows(db, kid.id, CashTransactionType.GIG_EARNED)
    assert len(rows) == 1 and rows[0].jar == "spend" and rows[0].amount_cents == 5000
    await _assert_invariant(db, kid.id)


# ── 3. Split application ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_split_credit_three_rows_rounding(db):
    fam = await _mk_family(db)
    await _entitle_plus(db, fam)
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, split_spend_pct=50, split_save_pct=30, split_share_pct=20)
    # 101¢ @ 50/30/20 → save 30, share 20, spend remainder 51.
    await CashService.award_gig_cash(db, kid.id, fam.id, None, 101, "gig")
    await db.commit()
    rows = await _rows(db, kid.id, CashTransactionType.GIG_EARNED)
    by_jar = {r.jar: r.amount_cents for r in rows}
    assert by_jar == {"spend": 51, "save": 30, "share": 20}
    assert sum(r.amount_cents for r in rows) == 101
    # Contiguous balance chain against the TOTAL.
    prev = 0
    for r in rows:
        assert r.balance_before == prev
        assert r.balance_after == prev + r.amount_cents
        prev = r.balance_after
    assert prev == 101
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_split_skips_zero_share_jars(db):
    fam = await _mk_family(db)
    await _entitle_plus(db, fam)
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, split_spend_pct=0, split_save_pct=100, split_share_pct=0)
    await CashService.award_gig_cash(db, kid.id, fam.id, None, 4000, "gig")
    await db.commit()
    rows = await _rows(db, kid.id, CashTransactionType.GIG_EARNED)
    assert len(rows) == 1 and rows[0].jar == "save" and rows[0].amount_cents == 4000
    await _assert_invariant(db, kid.id)


# ── 4. Negative debits — shared cascade ────────────────────────────────────────


@pytest.mark.asyncio
async def test_gig_clawback_cascades_spend_first(db):
    fam = await _mk_family(db)
    await _entitle_plus(db, fam)
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, split_spend_pct=40, split_save_pct=60, split_share_pct=0)
    await CashService.award_gig_cash(db, kid.id, fam.id, None, 10000, "gig")  # spend 4000 save 6000
    await db.commit()
    await CashService.award_gig_cash(db, kid.id, fam.id, None, -5000, "clawback")
    await db.commit()
    acct = (await db.execute(select(KidBankAccount).where(KidBankAccount.user_id == kid.id))).scalar_one()
    # spend 4000 fully drained, remaining 1000 taken from save.
    assert acct.spend_cents == 0 and acct.save_cents == 5000
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_negative_adjustment_cascades_into_save(db):
    """spend=0, save=200_00, adjust −100_00 must cascade into save (spec §11.4)."""
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=20000)
    parent = await _mk_parent(db, fam)
    # Move everything to save via a kid transfer so spend=0.
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 20000, kid.id)
    acct = (await db.execute(select(KidBankAccount).where(KidBankAccount.user_id == kid.id))).scalar_one()
    assert acct.spend_cents == 0 and acct.save_cents == 20000
    tx = await CashService.adjust(db, kid.id, fam.id, -10000, "correction", parent.id)
    assert tx.balance_after == 10000
    acct = (await db.execute(select(KidBankAccount).where(KidBankAccount.user_id == kid.id))).scalar_one()
    assert acct.spend_cents == 0 and acct.save_cents == 10000
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_adjustment_exceeding_total_floors_at_zero(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=5000)
    parent = await _mk_parent(db, fam)
    tx = await CashService.adjust(db, kid.id, fam.id, -10000, "big debit", parent.id)
    assert tx.balance_after == 0
    await db.refresh(kid)
    assert kid.cash_cents == 0
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_positive_adjustment_goes_to_spend(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=0)
    parent = await _mk_parent(db, fam)
    await CashService.adjust(db, kid.id, fam.id, 3000, "bonus", parent.id)
    acct = (await db.execute(select(KidBankAccount).where(KidBankAccount.user_id == kid.id))).scalar_one()
    assert acct.spend_cents == 3000 and acct.save_cents == 0
    await _assert_invariant(db, kid.id)


# ── 5. Jar transfers ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transfer_emits_paired_net_zero_rows(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=10000)
    await BankService.ensure_account(db, kid)
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 3000, kid.id)
    rows = await _rows(db, kid.id, CashTransactionType.JAR_TRANSFER)
    assert len(rows) == 2
    assert sum(r.amount_cents for r in rows) == 0
    assert {r.jar for r in rows} == {"spend", "save"}
    # Total is unchanged, so both rows stamp before == after == total.
    for r in rows:
        assert r.balance_before == r.balance_after == 10000
    acct = (await db.execute(select(KidBankAccount).where(KidBankAccount.user_id == kid.id))).scalar_one()
    assert acct.spend_cents == 7000 and acct.save_cents == 3000
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_transfer_insufficient_jar_balance_422(db):
    from fastapi import HTTPException

    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=1000)
    await BankService.ensure_account(db, kid)
    with pytest.raises(HTTPException) as ei:
        await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 5000, kid.id)
    assert ei.value.status_code == 422


# ── 6. Payout by jar ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payout_validates_jar_balance(db):
    from app.core.exceptions import ValidationException

    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=10000)
    parent = await _mk_parent(db, fam)
    # Put everything in save; a spend payout must now fail even though the
    # TOTAL is sufficient.
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 10000, kid.id)
    with pytest.raises(ValidationException):
        await CashService.record_payout(db, kid.id, fam.id, 5000, parent.id, jar="spend")
    # Settling Share/Save works against that jar.
    tx = await CashService.record_payout(db, kid.id, fam.id, 5000, parent.id, jar="save")
    assert tx.jar == "save" and tx.balance_after == 5000
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_legacy_payout_defaults_to_spend(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=8000)
    parent = await _mk_parent(db, fam)
    tx = await CashService.record_payout(db, kid.id, fam.id, 3000, parent.id)
    assert tx.jar == "spend" and tx.balance_after == 5000
    await _assert_invariant(db, kid.id)


# ── 7-9. Payday: allowance / interest / match (via _pay_one_kid, deterministic) ──


@pytest.mark.asyncio
async def test_payday_allowance_split(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, allowance_cents=10000,
                      split_spend_pct=50, split_save_pct=50, split_share_pct=0)
    paid = await BankService._pay_one_kid(db, fam.id, kid.id)
    assert paid == 1
    rows = await _rows(db, kid.id, CashTransactionType.ALLOWANCE)
    by_jar = {r.jar: r.amount_cents for r in rows}
    assert by_jar == {"spend": 5000, "save": 5000}
    acct = (await db.execute(select(KidBankAccount).where(KidBankAccount.user_id == kid.id))).scalar_one()
    assert acct.last_payday_at is not None
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_payday_interest_floor_on_save(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=20000)
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 20000, kid.id)
    await _set_config(db, kid, interest_rate_bps=100)  # 1%/wk
    await BankService._pay_one_kid(db, fam.id, kid.id)
    rows = await _rows(db, kid.id, CashTransactionType.INTEREST)
    assert len(rows) == 1 and rows[0].amount_cents == 200 and rows[0].jar == "save"
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_payday_interest_zero_rate_no_row(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=20000)
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 20000, kid.id)
    await BankService._pay_one_kid(db, fam.id, kid.id)
    assert await _rows(db, kid.id, CashTransactionType.INTEREST) == []


@pytest.mark.asyncio
async def test_payday_match_only_counts_kid_deposits(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=10000)
    parent = await _mk_parent(db, fam)
    await BankService.ensure_account(db, kid)
    # Kid-initiated save deposit (counts) + parent-forced save transfer (excluded).
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 10000, kid.id)
    await CashService.adjust(db, kid.id, fam.id, 5000, "topup", parent.id)  # spend +5000
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 5000, parent.id)  # parent-forced
    await _set_config(db, kid, match_pct=100)
    await BankService._pay_one_kid(db, fam.id, kid.id)
    rows = await _rows(db, kid.id, CashTransactionType.MATCH)
    assert len(rows) == 1 and rows[0].amount_cents == 10000  # only the kid's 10000
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_payday_match_cap_enforced(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=10000)
    await BankService.ensure_account(db, kid)
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 10000, kid.id)
    await _set_config(db, kid, match_pct=100, match_cap_cents=3000)
    await BankService._pay_one_kid(db, fam.id, kid.id)
    rows = await _rows(db, kid.id, CashTransactionType.MATCH)
    assert rows[0].amount_cents == 3000  # capped
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_payday_match_interest_compounds_same_payday(db):
    """Interest is on the POST-match Save balance (spec §D4)."""
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=10000)
    await BankService.ensure_account(db, kid)
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 10000, kid.id)  # save 10000
    await _set_config(db, kid, match_pct=50, interest_rate_bps=100)
    await BankService._pay_one_kid(db, fam.id, kid.id)
    match = (await _rows(db, kid.id, CashTransactionType.MATCH))[0].amount_cents
    interest = (await _rows(db, kid.id, CashTransactionType.INTEREST))[0].amount_cents
    assert match == 5000  # 50% of 10000
    assert interest == 150  # 1% of post-match 15000, not pre-match 10000
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_first_payday_null_window_matches_all_time(db):
    """last_payday_at IS NULL → all-time match window, not silently $0 (§D5)."""
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=10000)
    await BankService.ensure_account(db, kid)
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 10000, kid.id)
    await _set_config(db, kid, match_pct=50)
    acct = (await db.execute(select(KidBankAccount).where(KidBankAccount.user_id == kid.id))).scalar_one()
    assert acct.last_payday_at is None
    await BankService._pay_one_kid(db, fam.id, kid.id)
    rows = await _rows(db, kid.id, CashTransactionType.MATCH)
    assert len(rows) == 1 and rows[0].amount_cents == 5000


# ── 10-12. Sweep: gating / weekday / idempotency / timezone ─────────────────────


@pytest.mark.asyncio
async def test_sweep_pays_on_matching_local_weekday(db):
    tz_name, weekday = _tz_daytime()
    fam = await _mk_family(db, tz=tz_name)
    await _entitle_plus(db, fam)
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, allowance_cents=10000, payday_weekday=weekday)
    n = await BankService.run_payday_sweep(db)
    assert n == 1
    await db.refresh(kid)
    assert kid.cash_cents == 10000


@pytest.mark.asyncio
async def test_sweep_skips_wrong_weekday(db):
    tz_name, weekday = _tz_daytime()
    fam = await _mk_family(db, tz=tz_name)
    await _entitle_plus(db, fam)
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, allowance_cents=10000, payday_weekday=(weekday + 1) % 7)
    n = await BankService.run_payday_sweep(db)
    assert n == 0
    await db.refresh(kid)
    assert kid.cash_cents == 0


@pytest.mark.asyncio
async def test_sweep_free_family_skipped(db):
    tz_name, weekday = _tz_daytime()
    fam = await _mk_family(db, tz=tz_name)  # no subscription → free
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, allowance_cents=10000, payday_weekday=weekday)
    n = await BankService.run_payday_sweep(db)
    assert n == 0
    await db.refresh(kid)
    assert kid.cash_cents == 0


@pytest.mark.asyncio
async def test_sweep_skips_inactive_and_pending_kids(db):
    tz_name, weekday = _tz_daytime()
    fam = await _mk_family(db, tz=tz_name)
    await _entitle_plus(db, fam)
    inactive = await _mk_kid(db, fam, cash=0, active=False)
    pending = await _mk_kid(db, fam, cash=0, approval=APPROVAL_PENDING)
    for kid in (inactive, pending):
        await _set_config(db, kid, allowance_cents=10000, payday_weekday=weekday)
    n = await BankService.run_payday_sweep(db)
    assert n == 0


@pytest.mark.asyncio
async def test_sweep_idempotent_same_local_day(db):
    tz_name, weekday = _tz_daytime()
    fam = await _mk_family(db, tz=tz_name)
    await _entitle_plus(db, fam)
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, allowance_cents=10000, payday_weekday=weekday)
    assert await BankService.run_payday_sweep(db) == 1
    assert await BankService.run_payday_sweep(db) == 0  # second run same day = no-op
    await db.refresh(kid)
    assert kid.cash_cents == 10000


@pytest.mark.asyncio
async def test_sweep_timezone_bucketing(db):
    tz_name, weekday = _tz_daytime()
    fam_a = await _mk_family(db, tz=tz_name)
    fam_b = await _mk_family(db, tz=tz_name)
    await _entitle_plus(db, fam_a)
    await _entitle_plus(db, fam_b)
    kid_a = await _mk_kid(db, fam_a, cash=0)
    kid_b = await _mk_kid(db, fam_b, cash=0)
    await _set_config(db, kid_a, allowance_cents=10000, payday_weekday=weekday)
    await _set_config(db, kid_b, allowance_cents=10000, payday_weekday=(weekday + 3) % 7)
    n = await BankService.run_payday_sweep(db)
    assert n == 1
    await db.refresh(kid_a)
    await db.refresh(kid_b)
    assert kid_a.cash_cents == 10000 and kid_b.cash_cents == 0


# ── 12b. Credit-time split gating ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_free_plan_credit_ignores_stored_split(db):
    """A free family with a stored 50/30/20 split gets a single spend row."""
    fam = await _mk_family(db)  # free
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, split_spend_pct=50, split_save_pct=30, split_share_pct=20)
    await CashService.award_gig_cash(db, kid.id, fam.id, None, 10000, "gig")
    await db.commit()
    rows = await _rows(db, kid.id, CashTransactionType.GIG_EARNED)
    assert len(rows) == 1 and rows[0].jar == "spend" and rows[0].amount_cents == 10000
    await _assert_invariant(db, kid.id)


@pytest.mark.asyncio
async def test_plus_plan_credit_applies_stored_split(db):
    fam = await _mk_family(db)
    await _entitle_plus(db, fam)
    kid = await _mk_kid(db, fam, cash=0)
    await _set_config(db, kid, split_spend_pct=50, split_save_pct=30, split_share_pct=20)
    await CashService.award_gig_cash(db, kid.id, fam.id, None, 10000, "gig")
    await db.commit()
    rows = await _rows(db, kid.id, CashTransactionType.GIG_EARNED)
    assert len(rows) == 3
    await _assert_invariant(db, kid.id)


# ── 13. Notifications ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payday_notification_localized(db):
    from app.models.notification import Notification, NotificationType as NT

    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=0, lang="es")
    await _set_config(db, kid, allowance_cents=10000)
    await BankService._pay_one_kid(db, fam.id, kid.id)
    notes = (await db.execute(
        select(Notification).where(Notification.user_id == kid.id, Notification.type == NT.PAYDAY)
    )).scalars().all()
    assert len(notes) == 1
    assert "pago" in notes[0].title.lower()  # Spanish "¡Día de pago!"


@pytest.mark.asyncio
async def test_interest_only_notification_key(db):
    from app.models.notification import Notification, NotificationType as NT

    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=20000, lang="en")
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 20000, kid.id)
    await _set_config(db, kid, interest_rate_bps=100)  # interest only, no allowance/match
    await BankService._pay_one_kid(db, fam.id, kid.id)
    notes = (await db.execute(
        select(Notification).where(Notification.user_id == kid.id, Notification.type == NT.PAYDAY)
    )).scalars().all()
    assert len(notes) == 1
    assert "savings" in notes[0].title.lower()  # English interest-only copy


@pytest.mark.asyncio
async def test_request_notifies_all_parents(db):
    fam = await _mk_family(db)
    kid = await _mk_kid(db, fam, cash=5000)
    await _mk_parent(db, fam)
    await _mk_parent(db, fam)
    n = await BankService.request_save_withdrawal(db, kid, 3000, "para dulces")
    assert n == 2


# ── 14. Two-currency guard ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bank_flow_never_touches_points(db):
    fam = await _mk_family(db)
    await _entitle_plus(db, fam)
    kid = await _mk_kid(db, fam, cash=0)
    parent = await _mk_parent(db, fam)
    await _set_config(db, kid, split_spend_pct=50, split_save_pct=50, split_share_pct=0,
                      allowance_cents=5000, interest_rate_bps=100, match_pct=50)
    await CashService.award_gig_cash(db, kid.id, fam.id, None, 10000, "gig")
    await db.commit()
    await BankService.execute_transfer(db, kid.id, fam.id, "spend", "save", 1000, kid.id)
    await CashService.adjust(db, kid.id, fam.id, -500, "fix", parent.id)
    await BankService._pay_one_kid(db, fam.id, kid.id)
    await db.refresh(kid)
    assert kid.points == 0
    pt = (await db.execute(
        select(func.count()).select_from(PointTransaction).where(PointTransaction.user_id == kid.id)
    )).scalar()
    assert pt == 0
    await _assert_invariant(db, kid.id)


# ── 15. Premium unit (require_feature) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_feature_free_denied_plus_allowed(db):
    from fastapi import HTTPException
    from app.core.premium import require_feature

    fam_free = await _mk_family(db)
    parent_free = await _mk_parent(db, fam_free)
    with pytest.raises(HTTPException) as ei:
        await require_feature("family_bank_automation", db, parent_free)
    assert ei.value.status_code == 403

    fam_plus = await _mk_family(db)
    await _entitle_plus(db, fam_plus)
    parent_plus = await _mk_parent(db, fam_plus)
    plan = await require_feature("family_bank_automation", db, parent_plus)
    assert plan.limits.get("family_bank_automation") is True


# ── Route-level: settings validation, role + tenant gating, transfer approval ──
# These use the httpx client + conftest fixtures (test_family/test_parent_user/
# test_child_user, password123).
import pytest_asyncio
from httpx import AsyncClient


async def _login(client, email):
    res = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def parent_hdr(client, test_parent_user):
    return await _login(client, test_parent_user.email)


@pytest_asyncio.fixture
async def child_hdr(client, test_child_user):
    return await _login(client, test_child_user.email)


@pytest.mark.asyncio
async def test_route_settings_split_sum_422(client, test_child_user, parent_hdr):
    r = await client.put(
        f"/api/bank/settings/{test_child_user.id}",
        json={"split_spend_pct": 50, "split_save_pct": 30, "split_share_pct": 30},
        headers=parent_hdr,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_route_settings_interest_range_422(client, test_child_user, parent_hdr):
    r = await client.put(
        f"/api/bank/settings/{test_child_user.id}",
        json={"interest_rate_bps": 20000}, headers=parent_hdr,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_route_settings_weekday_range_422(client, test_child_user, parent_hdr):
    r = await client.put(
        f"/api/bank/settings/{test_child_user.id}",
        json={"payday_weekday": 9}, headers=parent_hdr,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_route_settings_requires_parent(client, test_child_user, child_hdr):
    r = await client.put(
        f"/api/bank/settings/{test_child_user.id}",
        json={"allowance_cents": 0}, headers=child_hdr,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_route_settings_cross_family_404(client, db_session, parent_hdr):
    other = Family(name="Other")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    other_kid = await _mk_kid(db_session, other, cash=0)
    r = await client.put(
        f"/api/bank/settings/{other_kid.id}",
        json={"allowance_cents": 0}, headers=parent_hdr,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_route_settings_reset_not_gated_on_free(client, test_child_user, parent_hdr):
    # Free plan, but resetting to no-op defaults must always be allowed.
    r = await client.put(
        f"/api/bank/settings/{test_child_user.id}",
        json={"allowance_cents": 0, "split_spend_pct": 100, "split_save_pct": 0,
              "split_share_pct": 0, "interest_rate_bps": 0, "match_pct": 0},
        headers=parent_hdr,
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_route_settings_enable_gated_on_free(client, test_child_user, parent_hdr):
    r = await client.put(
        f"/api/bank/settings/{test_child_user.id}",
        json={"allowance_cents": 5000}, headers=parent_hdr,
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "upgrade_required"


@pytest.mark.asyncio
async def test_route_transfer_kid_save_to_spend_approval(
    client, db_session, test_child_user, child_hdr, parent_hdr, test_parent_user
):
    test_child_user.cash_cents = 10000
    await db_session.commit()
    await BankService.ensure_account(db_session, test_child_user)
    await BankService.execute_transfer(
        db_session, test_child_user.id, test_child_user.family_id, "spend", "save", 5000,
        test_child_user.id,
    )
    # Flag on (default) → kid save→spend is blocked.
    r = await client.post(
        "/api/bank/transfer",
        json={"user_id": str(test_child_user.id), "from_jar": "save",
              "to_jar": "spend", "amount_cents": 1000},
        headers=child_hdr,
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "approval_required"

    # Parent may always do it.
    r = await client.post(
        "/api/bank/transfer",
        json={"user_id": str(test_child_user.id), "from_jar": "save",
              "to_jar": "spend", "amount_cents": 1000},
        headers=parent_hdr,
    )
    assert r.status_code == 200

    # Toggle approval off → kid self-serve.
    acct = await BankService.ensure_account(db_session, test_child_user)
    acct.save_withdrawal_requires_approval = False
    await db_session.commit()
    r = await client.post(
        "/api/bank/transfer",
        json={"user_id": str(test_child_user.id), "from_jar": "save",
              "to_jar": "spend", "amount_cents": 1000},
        headers=child_hdr,
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_route_kid_spend_to_save_self_serve(client, db_session, test_child_user, child_hdr):
    test_child_user.cash_cents = 8000
    await db_session.commit()
    await BankService.ensure_account(db_session, test_child_user)
    r = await client.post(
        "/api/bank/transfer",
        json={"user_id": str(test_child_user.id), "from_jar": "spend",
              "to_jar": "save", "amount_cents": 3000},
        headers=child_hdr,
    )
    assert r.status_code == 200
    assert r.json()["save_cents"] == 3000
