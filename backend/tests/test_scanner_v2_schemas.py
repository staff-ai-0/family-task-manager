import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.budget import (
    AccountCreate, TransactionItemRead, ItemTrend,
    AccountMatch, DupWarning, ScanReceiptResponse,
)
from app.schemas.a2a import A2AWebhookRead, A2AWebhookUpdate


def test_account_card_last4_validates_format():
    AccountCreate(name="x", type="credit", currency="MXN", card_last4="1234")
    with pytest.raises(PydanticValidationError):
        AccountCreate(name="x", type="credit", currency="MXN", card_last4="12a4")
    with pytest.raises(PydanticValidationError):
        AccountCreate(name="x", type="credit", currency="MXN", card_last4="12345")


def test_item_trend_round_trip():
    t = ItemTrend(normalized_name="leche alpura", avg_unit_cents=2800,
                  last_unit_cents=3200, pct_change=0.142, sample_size=8)
    assert t.pct_change == 0.142


def test_a2a_webhook_url_must_be_https():
    A2AWebhookUpdate(url="https://example.com/hook", enabled=True, rotate_secret=False)
    with pytest.raises(PydanticValidationError):
        A2AWebhookUpdate(url="http://example.com/hook", enabled=True, rotate_secret=False)


def test_scan_receipt_response_minimal():
    r = ScanReceiptResponse(
        success=True, transaction_id="00000000-0000-0000-0000-000000000000",
        confidence=0.9, items=[], trends=[], shopping_auto_checked=[],
        account_match=AccountMatch(strategy="last_used"),
    )
    assert r.success is True
    assert r.fx is None
