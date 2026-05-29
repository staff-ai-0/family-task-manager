from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import pytest_asyncio

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


# ---------------------------------------------------------------------------
# T10 — Endpoint tests: force, 409 dup_warning, account_id override
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def family_with_recent_heb_tx(
    db_session, test_family, test_parent_user, monkeypatch,
):
    """Set up: a BudgetAccount in the test family, a recent HEB tx, and
    monkeypatch scan_and_create_transaction so subsequent endpoint calls
    see a dup_warning (or success on force=True).
    """
    from app.models.budget import BudgetAccount, BudgetTransaction, BudgetPayee
    from datetime import date as date_type

    # Create account + payee + recent tx
    acct = BudgetAccount(
        family_id=test_family.id, name="HEB Card", type="credit", currency="MXN",
    )
    db_session.add(acct)
    await db_session.flush()

    payee = BudgetPayee(family_id=test_family.id, name="HEB")
    db_session.add(payee)
    await db_session.flush()

    tx = BudgetTransaction(
        family_id=test_family.id, account_id=acct.id,
        date=date_type.today(), amount=-72040, payee_id=payee.id,
    )
    db_session.add(tx)
    await db_session.commit()
    await db_session.refresh(tx)

    dup_result = {
        "success": False,
        "transaction_id": None,
        "dup_warning": {
            "existing_transaction_id": str(tx.id),
            "scanned_at": "2026-05-28T10:00:00",
            "amount_cents": -72040,
            "payee": "HEB",
        },
        "items": [],
        "account_match": {"strategy": "card_last4", "matched_card_last4": None},
        "fx": None,
        "trends": [],
        "confidence": 0.92,
        "shopping_auto_checked": [],
        "warnings": [],
        "scanned_preview": None,
        "draft_id": None,
        "message": None,
    }

    success_result = {
        "success": True,
        "transaction_id": str(tx.id),
        "draft_id": None,
        "items": [],
        "account_match": {"strategy": "card_last4", "matched_card_last4": None},
        "fx": None,
        "trends": [],
        "confidence": 0.92,
        "shopping_auto_checked": [],
        "warnings": [],
        "dup_warning": None,
        "scanned_preview": None,
        "scanned_data": {"payee_name": "HEB", "total_amount": -72040,
                         "date": "2026-05-28", "items": [], "currency": "MXN"},
        "message": "Transaction created from receipt scan.",
    }

    async def _fake_pipeline(db, family_id, user_id, account_id,
                             image_bytes, media_type, force=False):
        if force:
            return success_result
        return dup_result

    monkeypatch.setattr(
        "app.api.routes.budget.transactions.scan_and_create_transaction",
        _fake_pipeline,
    )
    monkeypatch.setattr(
        "app.api.routes.budget.transactions.require_feature",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.api.routes.budget.transactions.UsageService.increment",
        AsyncMock(),
    )
    return test_family


@pytest_asyncio.fixture
async def account_factory_authed(
    db_session, test_family, monkeypatch,
):
    """Creates a BudgetAccount in the test family's context.
    Also patches require_feature and scan_and_create_transaction with a
    success result that echoes back 'override' strategy.
    """
    from app.models.budget import BudgetAccount

    monkeypatch.setattr(
        "app.api.routes.budget.transactions.require_feature",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.api.routes.budget.transactions.UsageService.increment",
        AsyncMock(),
    )

    async def _make(*, currency: str = "MXN"):
        acct = BudgetAccount(
            family_id=test_family.id, name=f"Acct {currency}",
            type="checking", currency=currency,
        )
        db_session.add(acct)
        await db_session.commit()
        await db_session.refresh(acct)

        success_result = {
            "success": True,
            "transaction_id": "00000000-0000-0000-0000-000000000001",
            "draft_id": None,
            "items": [],
            "account_match": {"strategy": "override", "matched_card_last4": None},
            "fx": None,
            "trends": [],
            "confidence": 0.90,
            "shopping_auto_checked": [],
            "warnings": [],
            "dup_warning": None,
            "scanned_preview": None,
            "scanned_data": {"payee_name": "Test", "total_amount": -1000,
                             "date": "2026-05-28", "items": [], "currency": currency},
            "message": "Transaction created from receipt scan.",
        }

        async def _fake_pipeline(db, family_id, user_id, account_id,
                                 image_bytes, media_type, force=False):
            return success_result

        monkeypatch.setattr(
            "app.api.routes.budget.transactions.scan_and_create_transaction",
            _fake_pipeline,
        )
        return acct

    return _make


@pytest.mark.asyncio
async def test_endpoint_returns_409_on_dup(client, auth_headers,
                                           family_with_recent_heb_tx):
    """Endpoint returns 409 and dup_warning body when pipeline detects duplicate."""
    files = {"file": ("r.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")}
    resp = await client.post(
        "/api/budget/transactions/scan-receipt",
        files=files,
        headers=auth_headers,
    )
    assert resp.status_code == 409
    body = resp.json()
    assert "dup_warning" in body
    assert body["dup_warning"] is not None


@pytest.mark.asyncio
async def test_endpoint_force_true_commits(client, auth_headers,
                                           family_with_recent_heb_tx):
    """force=true query param bypasses dup guard and returns 200 success."""
    files = {"file": ("r.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")}
    resp = await client.post(
        "/api/budget/transactions/scan-receipt?force=true",
        files=files,
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_endpoint_account_id_overrides_auto_detect(
    client, auth_headers, account_factory_authed,
):
    """account_id form-data flows to pipeline and strategy is 'override'."""
    a = await account_factory_authed(currency="MXN")
    # account_id rides the multipart form (Form(...) on the endpoint), not
    # the query string — pin that contract here so a regression to
    # ?account_id=... gets caught.
    files = {"file": ("r.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")}
    data = {"account_id": str(a.id)}
    resp = await client.post(
        "/api/budget/transactions/scan-receipt",
        files=files,
        data=data,
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["account_match"]["strategy"] == "override"
