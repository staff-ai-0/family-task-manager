"""AccountMatchingService — pick an account from card_last4 + fallbacks."""

from uuid import uuid4
import pytest

from app.services.budget.account_matching_service import AccountMatchingService


@pytest.mark.asyncio
async def test_exact_card_last4_match(db, family, account_factory):
    a = await account_factory(family.id, name="MC 9222", card_last4="9222",
                               currency="MXN")
    pick = await AccountMatchingService.match(
        db, family.id, user_id=uuid4(),
        card_last4="9222", receipt_currency="MXN",
    )
    assert pick.strategy == "card_last4"
    assert pick.account_id == a.id


@pytest.mark.asyncio
async def test_ambiguous_card_last4_narrows_by_currency(db, family, account_factory):
    mxn = await account_factory(family.id, name="MC 9222 MXN",
                                 card_last4="9222", currency="MXN")
    usd = await account_factory(family.id, name="MC 9222 USD",
                                 card_last4="9222", currency="USD")
    pick = await AccountMatchingService.match(
        db, family.id, user_id=uuid4(),
        card_last4="9222", receipt_currency="USD",
    )
    assert pick.strategy == "card_last4"
    assert pick.account_id == usd.id


@pytest.mark.asyncio
async def test_falls_back_to_last_used_when_no_match(db, family, user, account_factory,
                                                     transaction_factory_for_account):
    a1 = await account_factory(family.id, name="A1", currency="MXN")
    a2 = await account_factory(family.id, name="A2", currency="MXN")
    # Most recent tx in family is on a2 (transaction_factory_for_account creates it)
    await transaction_factory_for_account(a2.id, user_id=user.id)
    pick = await AccountMatchingService.match(
        db, family.id, user_id=user.id,
        card_last4=None, receipt_currency="MXN",
    )
    assert pick.strategy == "last_used"
    assert pick.account_id == a2.id


@pytest.mark.asyncio
async def test_returns_none_when_no_accounts_at_all(db, family, user):
    pick = await AccountMatchingService.match(
        db, family.id, user_id=user.id,
        card_last4=None, receipt_currency="MXN",
    )
    assert pick.account_id is None
