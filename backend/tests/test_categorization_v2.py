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
    ensure_transfer_group,
    seed_default_categories,
)
from app.services.budget.report_service import ReportService
from app.services.budget.transfer_detector import (
    detect_transfer_category_name,
    resolve_transfer_category_for_kind,
    resolve_transfer_category_id,
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


# ── transfer detection ──────────────────────────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("Transferencia a BBVA MEXICO (cuenta 3235)", "Entre Cuentas"),
    ("Traspaso entre cuentas", "Entre Cuentas"),
    ("SPEI enviado a NU", "Entre Cuentas"),
    ("Pago de Tarjeta de Credito", "Pago de Tarjeta"),
    ("PAGO TDC BANAMEX", "Pago de Tarjeta"),
    ("Cajero Automático X95536", "Retiro de Efectivo"),
    ("Retiro de efectivo ATM", "Retiro de Efectivo"),
    ("HEB Bosque de las Lomas", None),
    ("CARNES FINAS SAN JUAN", None),
    ("", None),
])
def test_detect_transfer_category_name(text, expected):
    assert detect_transfer_category_name(text) == expected


@pytest.mark.asyncio
async def test_resolve_transfer_category_id_maps_to_group(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)
    cat_id = await resolve_transfer_category_id(
        db_session, test_family.id, "Transferencia a BBVA MEXICO",
    )
    assert cat_id is not None
    cat = await db_session.get(BudgetCategory, cat_id)
    group = await db_session.get(BudgetCategoryGroup, cat.group_id)
    assert group.is_transfer is True
    assert cat.name == "Entre Cuentas"


@pytest.mark.asyncio
async def test_resolve_transfer_returns_none_for_spending(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)
    cat_id = await resolve_transfer_category_id(
        db_session, test_family.id, "HEB Bosque de las Lomas",
    )
    assert cat_id is None


@pytest.mark.asyncio
async def test_ensure_transfer_group_idempotent_topup(db_session, test_family):
    # Seed WITHOUT transfer group by faking a pre-transfer tree: seed normally
    # (which now includes the group), then deleting it to simulate old data.
    await seed_default_categories(db_session, test_family.id)
    grp = (await db_session.execute(
        select(BudgetCategoryGroup).where(
            BudgetCategoryGroup.family_id == test_family.id,
            BudgetCategoryGroup.is_transfer.is_(True),
        )
    )).scalar_one()
    # Hard-delete to simulate a family seeded before transfer support.
    for c in (await db_session.execute(
        select(BudgetCategory).where(BudgetCategory.group_id == grp.id)
    )).scalars().all():
        await db_session.delete(c)
    await db_session.delete(grp)
    await db_session.commit()

    added = await ensure_transfer_group(db_session, test_family.id)
    assert added == 3
    # Second call is a no-op.
    assert await ensure_transfer_group(db_session, test_family.id) == 0


@pytest.mark.asyncio
async def test_backfill_detects_transfer_before_ai(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)
    acct = BudgetAccount(family_id=test_family.id, name="Card", type="checking")
    db_session.add(acct)
    await db_session.flush()
    payee = BudgetPayee(family_id=test_family.id, name="Transferencia a BBVA MEXICO (cuenta 3235)")
    db_session.add(payee)
    await db_session.flush()
    txn = BudgetTransaction(
        family_id=test_family.id, account_id=acct.id, payee_id=payee.id,
        date=date(2026, 4, 21), amount=-2100000,
    )
    db_session.add(txn)
    await db_session.commit()

    # AI must NOT be called — transfer detection short-circuits.
    with patch.object(CategoryAIService, "suggest") as mock_suggest:
        result = await CategoryAIService.backfill(db_session, test_family.id)
        mock_suggest.assert_not_called()

    assert result["applied"] == 1
    await db_session.refresh(txn)
    cat = await db_session.get(BudgetCategory, txn.category_id)
    group = await db_session.get(BudgetCategoryGroup, cat.group_id)
    assert group.is_transfer is True


@pytest.mark.asyncio
async def test_spending_report_excludes_transfers(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)
    acct = BudgetAccount(family_id=test_family.id, name="Card", type="checking")
    db_session.add(acct)
    await db_session.flush()

    # one real expense (Mandado), one transfer
    expense_cat = (await db_session.execute(
        select(BudgetCategory).join(BudgetCategoryGroup,
            BudgetCategory.group_id == BudgetCategoryGroup.id)
        .where(BudgetCategoryGroup.family_id == test_family.id,
               BudgetCategoryGroup.is_transfer.is_(False),
               BudgetCategoryGroup.is_income.is_(False)).limit(1)
    )).scalar_one()
    transfer_cat = (await db_session.execute(
        select(BudgetCategory).join(BudgetCategoryGroup,
            BudgetCategory.group_id == BudgetCategoryGroup.id)
        .where(BudgetCategoryGroup.family_id == test_family.id,
               BudgetCategoryGroup.is_transfer.is_(True)).limit(1)
    )).scalar_one()

    db_session.add(BudgetTransaction(
        family_id=test_family.id, account_id=acct.id, category_id=expense_cat.id,
        date=date(2026, 5, 10), amount=-50000,
    ))
    db_session.add(BudgetTransaction(
        family_id=test_family.id, account_id=acct.id, category_id=transfer_cat.id,
        date=date(2026, 5, 11), amount=-2100000,
    ))
    await db_session.commit()

    rep = await ReportService.get_spending_report(
        db_session, test_family.id, date(2026, 5, 1), date(2026, 5, 31),
        group_by="category",
    )
    names = {c["category_name"] for c in rep["categories"]}
    assert expense_cat.name in names
    assert transfer_cat.name not in names  # transfer excluded
    assert rep["total"] == -50000  # only the real expense


@pytest.mark.parametrize("kind,expected_cat", [
    ("transfer", "Entre Cuentas"),
    ("withdrawal", "Retiro de Efectivo"),
    ("card_payment", "Pago de Tarjeta"),
])
@pytest.mark.asyncio
async def test_resolve_transfer_for_kind(db_session, test_family, kind, expected_cat):
    await seed_default_categories(db_session, test_family.id)
    cat_id = await resolve_transfer_category_for_kind(db_session, test_family.id, kind)
    assert cat_id is not None
    cat = await db_session.get(BudgetCategory, cat_id)
    assert cat.name == expected_cat


@pytest.mark.asyncio
async def test_resolve_transfer_for_kind_purchase_is_none(db_session, test_family):
    await seed_default_categories(db_session, test_family.id)
    # purchase / deposit / fee are NOT transfers → normal categorization flow
    assert await resolve_transfer_category_for_kind(db_session, test_family.id, "purchase") is None
    assert await resolve_transfer_category_for_kind(db_session, test_family.id, "fee") is None
