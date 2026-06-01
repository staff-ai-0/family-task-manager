"""Tests for Actual-style categorization: default seeding, payee learning,
AI suggestion mapping, and the backfill precedence chain."""

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app.models.budget import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetPayee,
    BudgetTransaction,
)
from app.services.budget.category_ai_service import CategoryAIService
from app.services.budget.default_categories import (
    DEFAULT_CATEGORY_TREE,
    seed_default_categories,
)


@pytest.mark.asyncio
async def test_seed_default_categories_creates_tree(db_session, test_family):
    created = await seed_default_categories(db_session, test_family.id)
    assert created > 0

    groups = (await db_session.execute(
        select(func.count()).select_from(BudgetCategoryGroup).where(
            BudgetCategoryGroup.family_id == test_family.id
        )
    )).scalar_one()
    assert groups == len(DEFAULT_CATEGORY_TREE)

    income = (await db_session.execute(
        select(BudgetCategoryGroup).where(
            BudgetCategoryGroup.family_id == test_family.id,
            BudgetCategoryGroup.is_income.is_(True),
        )
    )).scalars().all()
    assert len(income) == 1  # exactly one income group


@pytest.mark.asyncio
async def test_seed_default_categories_is_idempotent(db_session, test_family):
    first = await seed_default_categories(db_session, test_family.id)
    second = await seed_default_categories(db_session, test_family.id)
    assert first > 0
    assert second == 0  # no-op on second call

    total = (await db_session.execute(
        select(func.count()).select_from(BudgetCategory).where(
            BudgetCategory.family_id == test_family.id
        )
    )).scalar_one()
    assert total == first  # not doubled


@pytest.mark.asyncio
async def test_ai_suggest_maps_index_to_category(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)
    # Grab an expense category to be the "right" answer (index 1 of the list).
    cats = await CategoryAIService._load_categories(
        db_session, test_family.id, is_income=False
    )
    assert cats, "expected expense categories after seeding"
    target_id = cats[0][0]

    class _Msg:
        content = '{"index": 1}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    with patch("app.services.budget.category_ai_service.OpenAI") as mock_openai, \
         patch("app.services.budget.category_ai_service.settings") as mock_settings:
        mock_settings.LITELLM_API_KEY = "sk-test"
        mock_settings.LITELLM_API_BASE = "http://proxy"
        mock_openai.return_value.chat.completions.create.return_value = _Resp()

        result = await CategoryAIService.suggest(
            db_session, test_family.id, "PETRO 7 PETROMAX", ["MAGNA"],
        )
    assert result == target_id


@pytest.mark.asyncio
async def test_ai_suggest_null_index_returns_none(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)

    class _Msg:
        content = '{"index": null}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    with patch("app.services.budget.category_ai_service.OpenAI") as mock_openai, \
         patch("app.services.budget.category_ai_service.settings") as mock_settings:
        mock_settings.LITELLM_API_KEY = "sk-test"
        mock_settings.LITELLM_API_BASE = "http://proxy"
        mock_openai.return_value.chat.completions.create.return_value = _Resp()

        result = await CategoryAIService.suggest(
            db_session, test_family.id, "UNKNOWN MERCHANT", [],
        )
    assert result is None


@pytest.mark.asyncio
async def test_ai_suggest_no_api_key_returns_none(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)
    with patch("app.services.budget.category_ai_service.settings") as mock_settings:
        mock_settings.LITELLM_API_KEY = ""
        result = await CategoryAIService.suggest(
            db_session, test_family.id, "PETRO 7", ["MAGNA"],
        )
    assert result is None


@pytest.mark.asyncio
async def test_backfill_uses_payee_default_before_ai(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)
    cat = (await db_session.execute(
        select(BudgetCategory).where(BudgetCategory.family_id == test_family.id).limit(1)
    )).scalar_one()

    acct = BudgetAccount(family_id=test_family.id, name="Card", type="checking")
    db_session.add(acct)
    await db_session.flush()

    # Payee already has a learned default — backfill must use it, NOT call AI.
    payee = BudgetPayee(family_id=test_family.id, name="OXXO", default_category_id=cat.id)
    db_session.add(payee)
    await db_session.flush()

    txn = BudgetTransaction(
        family_id=test_family.id, account_id=acct.id, payee_id=payee.id,
        date=date(2026, 5, 1), amount=-5000,
    )
    db_session.add(txn)
    await db_session.commit()

    with patch.object(CategoryAIService, "suggest") as mock_suggest:
        result = await CategoryAIService.backfill(db_session, test_family.id)
        mock_suggest.assert_not_called()

    assert result["applied"] == 1
    await db_session.refresh(txn)
    assert txn.category_id == cat.id


@pytest.mark.asyncio
async def test_backfill_learns_payee_default_from_ai(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)
    cat = (await db_session.execute(
        select(BudgetCategory).where(BudgetCategory.family_id == test_family.id).limit(1)
    )).scalar_one()

    acct = BudgetAccount(family_id=test_family.id, name="Card", type="checking")
    db_session.add(acct)
    await db_session.flush()
    payee = BudgetPayee(family_id=test_family.id, name="NEW MERCHANT")
    db_session.add(payee)
    await db_session.flush()
    txn = BudgetTransaction(
        family_id=test_family.id, account_id=acct.id, payee_id=payee.id,
        date=date(2026, 5, 1), amount=-9900,
    )
    db_session.add(txn)
    await db_session.commit()

    async def _fake_suggest(*a, **k):
        return cat.id

    with patch.object(CategoryAIService, "suggest", side_effect=_fake_suggest):
        result = await CategoryAIService.backfill(db_session, test_family.id)

    assert result["applied"] == 1
    await db_session.refresh(txn)
    await db_session.refresh(payee)
    assert txn.category_id == cat.id
    assert payee.default_category_id == cat.id  # learned for next time
