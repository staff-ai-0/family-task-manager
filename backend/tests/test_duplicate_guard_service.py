"""DuplicateGuardService — flag same-payee same-amount recent receipts."""

from datetime import datetime, timedelta, timezone
import pytest

from app.services.budget.duplicate_guard_service import DuplicateGuardService


@pytest.mark.asyncio
async def test_flags_same_payee_same_amount_within_60s(
    db, family, payee, transaction_factory_with_payee,
):
    recent = await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    dup = await DuplicateGuardService.check(
        db, family.id, payee_id=payee.id, amount_cents=-72040,
    )
    assert dup is not None
    assert dup.existing_transaction_id == recent.id


@pytest.mark.asyncio
async def test_does_not_flag_after_60s(
    db, family, payee, transaction_factory_with_payee,
):
    await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=90),
    )
    dup = await DuplicateGuardService.check(
        db, family.id, payee_id=payee.id, amount_cents=-72040,
    )
    assert dup is None


@pytest.mark.asyncio
async def test_does_not_flag_when_amount_differs_more_than_1pct(
    db, family, payee, transaction_factory_with_payee,
):
    await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    dup = await DuplicateGuardService.check(
        db, family.id, payee_id=payee.id, amount_cents=-80000,
    )
    assert dup is None


@pytest.mark.asyncio
async def test_does_not_cross_families(
    db, family, other_family, payee, transaction_factory_with_payee,
):
    await transaction_factory_with_payee(
        other_family.id, payee.id, amount=-72040,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    dup = await DuplicateGuardService.check(
        db, family.id, payee_id=payee.id, amount_cents=-72040,
    )
    assert dup is None
