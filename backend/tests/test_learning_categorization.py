"""Tests for P2 learning categorization.

Covers three deliverables:
  1. Few-shot context assembled from a family's payee→category history
     (CategorizationRuleService.recent_payee_category_pairs / format_category_fewshot).
  2. Auto-suggesting a BudgetCategorizationRule after repeated identical
     categorizations (CategorizationRuleService.suggest_rules_from_history).
  3. The receipt-scanner prompt carrying that few-shot context, and the scan
     pipeline honoring the model's learned `suggested_category`.

All assertions verify family_id isolation where relevant.
"""

from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.family import Family
from app.models.budget import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetCategorizationRule,
    BudgetPayee,
    BudgetTransaction,
)
from app.services.budget.categorization_rule_service import CategorizationRuleService
from app.services.budget.receipt_scanner_service import (
    ScannedReceipt,
    scan_receipt,
    scan_and_create_transaction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_category(db, family_id, name):
    group = BudgetCategoryGroup(family_id=family_id, name=f"{name} Group")
    db.add(group)
    await db.flush()
    cat = BudgetCategory(family_id=family_id, group_id=group.id, name=name)
    db.add(cat)
    await db.flush()
    return cat


async def _make_account(db, family_id, name="Card"):
    acct = BudgetAccount(family_id=family_id, name=name, type="checking", currency="MXN")
    db.add(acct)
    await db.flush()
    return acct


async def _make_payee(db, family_id, name):
    payee = BudgetPayee(family_id=family_id, name=name)
    db.add(payee)
    await db.flush()
    return payee


async def _make_txn(db, family_id, account_id, payee_id, category_id, amount=-5000, d=None):
    txn = BudgetTransaction(
        family_id=family_id,
        account_id=account_id,
        payee_id=payee_id,
        category_id=category_id,
        date=d or date(2026, 5, 1),
        amount=amount,
    )
    db.add(txn)
    await db.flush()
    return txn


# ---------------------------------------------------------------------------
# Few-shot assembly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fewshot_assembled_from_history(db_session, test_family):
    fid = test_family.id
    acct = await _make_account(db_session, fid)
    mandado = await _make_category(db_session, fid, "Mandado")
    entret = await _make_category(db_session, fid, "Entretenimiento")
    heb = await _make_payee(db_session, fid, "HEB")
    netflix = await _make_payee(db_session, fid, "Netflix")

    await _make_txn(db_session, fid, acct.id, heb.id, mandado.id)
    await _make_txn(db_session, fid, acct.id, heb.id, mandado.id)
    await _make_txn(db_session, fid, acct.id, netflix.id, entret.id)
    await db_session.commit()

    pairs = await CategorizationRuleService.recent_payee_category_pairs(db_session, fid)
    got = {(p["payee"], p["category"]) for p in pairs}
    assert ("HEB", "Mandado") in got
    assert ("Netflix", "Entretenimiento") in got
    # Distinct pairs only — HEB×Mandado collapses to one entry despite 2 txns.
    assert len(pairs) == 2

    block = CategorizationRuleService.format_category_fewshot(pairs)
    assert "HEB → Mandado" in block
    assert "Netflix → Entretenimiento" in block
    assert block.startswith("Known merchant→category history")


@pytest.mark.asyncio
async def test_fewshot_empty_when_no_history(db_session, test_family):
    pairs = await CategorizationRuleService.recent_payee_category_pairs(
        db_session, test_family.id
    )
    assert pairs == []
    assert CategorizationRuleService.format_category_fewshot(pairs) == ""


@pytest.mark.asyncio
async def test_fewshot_is_family_scoped(db_session, test_family):
    """Family B's history must not leak into family A's few-shot context."""
    other = Family(name="Other Family")
    db_session.add(other)
    await db_session.flush()

    acct_b = await _make_account(db_session, other.id, "B Card")
    cat_b = await _make_category(db_session, other.id, "Servicios")
    payee_b = await _make_payee(db_session, other.id, "CFE")
    await _make_txn(db_session, other.id, acct_b.id, payee_b.id, cat_b.id)
    await db_session.commit()

    pairs = await CategorizationRuleService.recent_payee_category_pairs(
        db_session, test_family.id
    )
    assert pairs == []


# ---------------------------------------------------------------------------
# Rule suggestions from repeated corrections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_rule_after_threshold(db_session, test_family):
    fid = test_family.id
    acct = await _make_account(db_session, fid)
    mandado = await _make_category(db_session, fid, "Mandado")
    snacks = await _make_category(db_session, fid, "Snacks")
    heb = await _make_payee(db_session, fid, "HEB")
    oxxo = await _make_payee(db_session, fid, "OXXO")

    # HEB categorized to Mandado twice → meets default min_count=2.
    await _make_txn(db_session, fid, acct.id, heb.id, mandado.id)
    await _make_txn(db_session, fid, acct.id, heb.id, mandado.id)
    # OXXO categorized only once → below threshold, no suggestion.
    await _make_txn(db_session, fid, acct.id, oxxo.id, snacks.id)
    await db_session.commit()

    suggestions = await CategorizationRuleService.suggest_rules_from_history(
        db_session, fid, min_count=2
    )
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s["payee_id"] == heb.id
    assert s["payee_name"] == "HEB"
    assert s["category_id"] == mandado.id
    assert s["category_name"] == "Mandado"
    assert s["match_count"] == 2


@pytest.mark.asyncio
async def test_suggest_rule_picks_dominant_category(db_session, test_family):
    fid = test_family.id
    acct = await _make_account(db_session, fid)
    mandado = await _make_category(db_session, fid, "Mandado")
    otros = await _make_category(db_session, fid, "Otros")
    heb = await _make_payee(db_session, fid, "HEB")

    # 3 → Mandado, 2 → Otros. Dominant category wins.
    for _ in range(3):
        await _make_txn(db_session, fid, acct.id, heb.id, mandado.id)
    for _ in range(2):
        await _make_txn(db_session, fid, acct.id, heb.id, otros.id)
    await db_session.commit()

    suggestions = await CategorizationRuleService.suggest_rules_from_history(
        db_session, fid, min_count=2
    )
    # One suggestion per payee, dominant category.
    assert len(suggestions) == 1
    assert suggestions[0]["category_id"] == mandado.id
    assert suggestions[0]["match_count"] == 3


@pytest.mark.asyncio
async def test_suggest_rule_excludes_existing_exact_payee_rule(db_session, test_family):
    fid = test_family.id
    acct = await _make_account(db_session, fid)
    mandado = await _make_category(db_session, fid, "Mandado")
    heb = await _make_payee(db_session, fid, "HEB")
    await _make_txn(db_session, fid, acct.id, heb.id, mandado.id)
    await _make_txn(db_session, fid, acct.id, heb.id, mandado.id)

    # Already-automated payee → no re-suggestion.
    rule = BudgetCategorizationRule(
        family_id=fid, category_id=mandado.id, rule_type="exact",
        match_field="payee", pattern="HEB", enabled=True, priority=0,
    )
    db_session.add(rule)
    await db_session.commit()

    suggestions = await CategorizationRuleService.suggest_rules_from_history(
        db_session, fid, min_count=2
    )
    assert suggestions == []


@pytest.mark.asyncio
async def test_suggest_rule_is_family_scoped(db_session, test_family):
    other = Family(name="Other Family")
    db_session.add(other)
    await db_session.flush()

    acct_b = await _make_account(db_session, other.id, "B Card")
    cat_b = await _make_category(db_session, other.id, "Mandado")
    payee_b = await _make_payee(db_session, other.id, "HEB")
    for _ in range(3):
        await _make_txn(db_session, other.id, acct_b.id, payee_b.id, cat_b.id)
    await db_session.commit()

    suggestions = await CategorizationRuleService.suggest_rules_from_history(
        db_session, test_family.id, min_count=2
    )
    assert suggestions == []


# ---------------------------------------------------------------------------
# Few-shot injected into the receipt-scanner prompt
# ---------------------------------------------------------------------------


def _mock_completion(content: str):
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    return completion


@pytest.mark.asyncio
async def test_scan_receipt_prompt_includes_fewshot_and_parses_suggested_category():
    hints = (
        "Known merchant→category history for this family "
        "(use as a hint when guessing the category):\n- HEB → Mandado"
    )
    model_json = (
        '{"date": "2026-03-15", "total_amount": -15050, "payee_name": "HEB", '
        '"items": [], "currency": "MXN", "confidence": 0.9, '
        '"suggested_category": "Mandado"}'
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(model_json)

    with patch("app.services.budget.receipt_scanner_service.settings") as mock_settings, \
         patch("app.services.budget.receipt_scanner_service.OpenAI") as mock_openai:
        mock_settings.LITELLM_API_KEY = "sk-fake"
        mock_settings.LITELLM_API_BASE = "http://proxy"
        mock_openai.return_value = mock_client

        result = await scan_receipt(
            b"img", "image/jpeg", category_hints=hints,
        )

        call_args = mock_client.chat.completions.create.call_args
        text_part = next(
            c for c in call_args.kwargs["messages"][0]["content"]
            if c["type"] == "text"
        )
        assert "HEB → Mandado" in text_part["text"]
        assert "suggested_category" in text_part["text"]

    assert result.suggested_category == "Mandado"


@pytest.mark.asyncio
async def test_scan_receipt_no_hints_leaves_prompt_clean():
    """Without hints the prompt is the base extraction prompt (no fewshot block)."""
    model_json = (
        '{"date": "2026-03-15", "total_amount": -15050, "payee_name": "HEB", '
        '"items": [], "currency": "MXN", "confidence": 0.9}'
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mock_completion(model_json)

    with patch("app.services.budget.receipt_scanner_service.settings") as mock_settings, \
         patch("app.services.budget.receipt_scanner_service.OpenAI") as mock_openai:
        mock_settings.LITELLM_API_KEY = "sk-fake"
        mock_settings.LITELLM_API_BASE = "http://proxy"
        mock_openai.return_value = mock_client

        result = await scan_receipt(b"img", "image/jpeg")

        call_args = mock_client.chat.completions.create.call_args
        text_part = next(
            c for c in call_args.kwargs["messages"][0]["content"]
            if c["type"] == "text"
        )
        assert "Known merchant→category history" not in text_part["text"]

    assert result.suggested_category is None


# ---------------------------------------------------------------------------
# Pipeline honors the learned suggested_category
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_uses_suggested_category(db_session, test_family):
    fid = test_family.id
    acct = await _make_account(db_session, fid)
    mandado = await _make_category(db_session, fid, "Mandado")
    await db_session.commit()

    receipt = ScannedReceipt(
        date=date(2026, 3, 20),
        total_amount=-8500,
        payee_name="Tienda Nueva",
        items=[],
        currency="MXN",
        raw_text="",
        confidence=0.9,
        suggested_category="Mandado",
    )

    with patch(
        "app.services.budget.receipt_scanner_service.scan_receipt",
        return_value=receipt,
    ):
        result = await scan_and_create_transaction(
            db=db_session,
            family_id=fid,
            account_id=acct.id,
            image_bytes=b"x",
            media_type="image/jpeg",
        )

    assert result["success"] is True
    txn = (await db_session.execute(
        select(BudgetTransaction).where(
            BudgetTransaction.id == result["transaction_id"]
        )
    )).scalar_one()
    assert txn.category_id == mandado.id


@pytest.mark.asyncio
async def test_pipeline_ignores_unknown_suggested_category(db_session, test_family):
    """A hallucinated category name resolves to nothing → header stays uncategorized
    (no AI key configured in tests, so it falls through cleanly)."""
    fid = test_family.id
    acct = await _make_account(db_session, fid)
    await _make_category(db_session, fid, "Mandado")
    await db_session.commit()

    receipt = ScannedReceipt(
        date=date(2026, 3, 20),
        total_amount=-8500,
        payee_name="Tienda Nueva",
        items=[],
        currency="MXN",
        raw_text="",
        confidence=0.9,
        suggested_category="Categoria Que No Existe",
    )

    from app.services.budget.category_ai_service import CategoryAIService

    async def _no_ai(*a, **k):
        return None

    with patch(
        "app.services.budget.receipt_scanner_service.scan_receipt",
        return_value=receipt,
    ), patch.object(CategoryAIService, "suggest", side_effect=_no_ai):
        result = await scan_and_create_transaction(
            db=db_session,
            family_id=fid,
            account_id=acct.id,
            image_bytes=b"x",
            media_type="image/jpeg",
        )

    assert result["success"] is True
    txn = (await db_session.execute(
        select(BudgetTransaction).where(
            BudgetTransaction.id == result["transaction_id"]
        )
    )).scalar_one()
    assert txn.category_id is None
