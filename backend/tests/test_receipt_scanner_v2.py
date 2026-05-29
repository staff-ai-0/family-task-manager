from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.budget.receipt_scanner_service import (
    scan_and_create_transaction,
    scan_receipt,
)


def _mock_vision_json(payload: dict):
    """Build an OpenAI Chat completion mock returning JSON-as-text."""
    import json as _json
    msg = MagicMock()
    msg.content = _json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    return completion


@pytest.mark.asyncio
async def test_scan_extracts_card_last4_iva_and_items(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.LITELLM_API_KEY", "test-key")
    monkeypatch.setattr("app.core.config.settings.LITELLM_API_BASE",
                        "http://litellm")

    fake = _mock_vision_json({
        "date": "2026-05-28",
        "total_amount": -72040,
        "iva_cents": 9683,
        "payee_name": "HEB",
        "card_last4": "9222",
        "currency": "MXN",
        "items": [
            {"name": "Leche Alpura 1L", "qty": 2,
             "unit_price_cents": 3200, "total_cents": 6400,
             "brand": "Alpura", "raw_text": "LECHE ALPURA 1L 2 X 32.00 64.00"},
        ],
        "confidence": 0.92,
    })
    fake_client = MagicMock()
    fake_client.chat.completions.create = MagicMock(return_value=fake)
    with patch("app.services.budget.receipt_scanner_service.OpenAI",
               return_value=fake_client):
        result = await scan_receipt(b"jpegbytes", "image/jpeg")

    assert result.card_last4 == "9222"
    assert result.iva_cents == 9683
    assert len(result.items) == 1
    item = result.items[0]
    assert item["brand"] == "Alpura"
    assert item["qty"] == 2
    assert item["unit_price_cents"] == 3200
    assert item["raw_text"].startswith("LECHE ALPURA")


# ---------------------------------------------------------------------------
# T9 — full 7-stage scan_and_create_transaction pipeline
# ---------------------------------------------------------------------------


def _fake_receipt(**overrides):
    """Build a MagicMock ScannedReceipt-shape with sensible defaults."""
    fields = {
        "date": date(2026, 5, 28),
        "total_amount": -72040,
        "payee_name": "HEB",
        "items": [],
        "currency": "MXN",
        "raw_text": "",
        "confidence": 0.92,
        "card_last4": None,
        "iva_cents": None,
    }
    fields.update(overrides)
    return MagicMock(**fields)


@pytest.mark.asyncio
async def test_pipeline_creates_tx_with_items_and_fx(
    db, family, user, account_factory, monkeypatch,
):
    """Happy path: vision → card_last4 match → tx+item persisted."""
    mxn = await account_factory(
        family.id, name="MC MXN", card_last4="9222", currency="MXN",
    )

    fake_receipt = _fake_receipt(
        card_last4="9222",
        iva_cents=9683,
        items=[
            {"name": "Leche", "qty": 2, "unit_price_cents": 3200,
             "total_cents": 6400, "raw_text": "LECHE 2x 64.00"},
        ],
    )

    async def fake_scan(_b, _t):
        return fake_receipt

    monkeypatch.setattr(
        "app.services.budget.receipt_scanner_service.scan_receipt", fake_scan,
    )

    result = await scan_and_create_transaction(
        db=db,
        family_id=family.id,
        user_id=user.id,
        account_id=None,
        image_bytes=b"x",
        media_type="image/jpeg",
        force=False,
    )
    assert result["success"] is True
    assert result["transaction_id"] is not None
    assert len(result["items"]) == 1
    assert result["account_match"]["strategy"] == "card_last4"

    # Verify the transaction landed on the matched MXN account.
    from sqlalchemy import select
    from app.models.budget import BudgetTransaction
    row = (await db.execute(
        select(BudgetTransaction).where(
            BudgetTransaction.id == result["transaction_id"]
        )
    )).scalar_one()
    assert row.account_id == mxn.id
    assert row.card_last4 == "9222"
    assert row.iva_cents == 9683


@pytest.mark.asyncio
async def test_pipeline_returns_dup_warning_without_committing(
    db, family, user, account_factory, payee,
    transaction_factory_with_payee, monkeypatch,
):
    """Same-payee same-amount recent tx → returns dup_warning, no new tx persisted."""
    await account_factory(
        family.id, name="MC MXN", card_last4="9222", currency="MXN",
    )
    # Seed a recent matching transaction
    await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
    )

    fake_receipt = _fake_receipt(
        card_last4="9222",
        payee_name=payee.name,
    )

    async def fake_scan(_b, _t):
        return fake_receipt

    monkeypatch.setattr(
        "app.services.budget.receipt_scanner_service.scan_receipt", fake_scan,
    )

    # Count tx rows before the call
    from sqlalchemy import func, select
    from app.models.budget import BudgetTransaction
    before = (await db.execute(
        select(func.count()).select_from(BudgetTransaction).where(
            BudgetTransaction.family_id == family.id,
        )
    )).scalar_one()

    result = await scan_and_create_transaction(
        db=db,
        family_id=family.id,
        user_id=user.id,
        account_id=None,
        image_bytes=b"x",
        media_type="image/jpeg",
        force=False,
    )
    assert result["success"] is False
    assert result["dup_warning"] is not None
    assert result["transaction_id"] is None

    # No new transaction should have been persisted.
    after = (await db.execute(
        select(func.count()).select_from(BudgetTransaction).where(
            BudgetTransaction.family_id == family.id,
        )
    )).scalar_one()
    assert after == before


@pytest.mark.asyncio
async def test_force_true_bypasses_duplicate_guard(
    db, family, user, account_factory, payee,
    transaction_factory_with_payee, monkeypatch,
):
    """force=True skips the dup-guard check and commits the transaction."""
    await account_factory(
        family.id, name="MC MXN", card_last4="9222", currency="MXN",
    )
    await transaction_factory_with_payee(
        family.id, payee.id, amount=-72040,
    )

    fake_receipt = _fake_receipt(
        card_last4="9222",
        payee_name=payee.name,
    )

    async def fake_scan(_b, _t):
        return fake_receipt

    monkeypatch.setattr(
        "app.services.budget.receipt_scanner_service.scan_receipt", fake_scan,
    )

    result = await scan_and_create_transaction(
        db=db,
        family_id=family.id,
        user_id=user.id,
        account_id=None,
        image_bytes=b"x",
        media_type="image/jpeg",
        force=True,
    )
    assert result["success"] is True
    assert result["transaction_id"] is not None
    assert result.get("dup_warning") is None


@pytest.mark.asyncio
async def test_pipeline_stores_fx_when_currencies_differ(
    db, family, user, account_factory, monkeypatch,
):
    """USD receipt on a MXN account: rate stored, original amount preserved."""
    mxn = await account_factory(
        family.id, name="MC MXN", card_last4=None, currency="MXN",
    )

    fake_receipt = _fake_receipt(
        total_amount=-4200,
        payee_name="WALMART US",
        currency="USD",
        card_last4=None,
    )

    async def fake_scan(_b, _t):
        return fake_receipt

    monkeypatch.setattr(
        "app.services.budget.receipt_scanner_service.scan_receipt", fake_scan,
    )

    from decimal import Decimal

    async def fake_fx(*_a, **_k):
        return Decimal("17.15")

    monkeypatch.setattr(
        "app.services.fx_service.FXService.get_rate", fake_fx,
    )

    # Pro plan: fx_cross_charge is allowed
    monkeypatch.setattr(
        "app.services.budget.receipt_scanner_service.is_feature_enabled",
        AsyncMock(return_value=True),
    )

    result = await scan_and_create_transaction(
        db=db,
        family_id=family.id,
        user_id=user.id,
        account_id=mxn.id,
        image_bytes=b"x",
        media_type="image/jpeg",
        force=False,
    )
    assert result["success"] is True
    assert result["fx"] is not None
    assert result["fx"]["rate"] == "17.15"
    assert result["fx"]["original_currency"] == "USD"
    assert result["fx"]["original_amount_cents"] == -4200

    # Verify the persisted transaction reflects the converted amount + FX cols.
    from sqlalchemy import select
    from app.models.budget import BudgetTransaction
    row = (await db.execute(
        select(BudgetTransaction).where(
            BudgetTransaction.id == result["transaction_id"]
        )
    )).scalar_one()
    assert row.original_amount_cents == -4200
    assert row.original_currency == "USD"
    assert str(row.fx_rate) in ("17.150000", "17.15")  # numeric(12,6)
    # -4200 * 17.15 = -72030 (with ROUND_HALF_UP)
    assert row.amount in (-72030, -72031)
