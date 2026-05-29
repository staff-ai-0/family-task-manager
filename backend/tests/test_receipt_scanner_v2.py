from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.budget.receipt_scanner_service import scan_receipt


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
