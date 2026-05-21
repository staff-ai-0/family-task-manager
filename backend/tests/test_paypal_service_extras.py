"""Tests for PayPalService methods added/rewritten in v1.

The v2 PayPal Billing Subscriptions API is reached via direct HTTP through
_PayPalV2HTTP — these tests patch that helper rather than the legacy
paypalrestsdk SDK.
"""
from unittest.mock import patch

import pytest

from app.core.exceptions import NotFoundException, ValidationException
from app.services.paypal_service import PayPalService


def test_get_subscription_returns_dict():
    fake_response = {
        "id": "I-TESTSUB123",
        "status": "ACTIVE",
        "plan_id": "P-PLAN-PLUS-MONTHLY",
        "billing_info": {"next_billing_time": "2026-06-21T00:00:00Z"},
    }
    with patch(
        "app.services.paypal_service._PayPalV2HTTP.get",
        return_value=fake_response,
    ):
        out = PayPalService.get_subscription("I-TESTSUB123")

    assert out["subscription_id"] == "I-TESTSUB123"
    assert out["status"] == "ACTIVE"
    assert out["plan_id"] == "P-PLAN-PLUS-MONTHLY"
    assert out["next_billing_at"] == "2026-06-21T00:00:00Z"


def test_get_subscription_raises_not_found():
    with patch(
        "app.services.paypal_service._PayPalV2HTTP.get",
        side_effect=NotFoundException("404"),
    ):
        with pytest.raises(NotFoundException):
            PayPalService.get_subscription("I-MISSING")


def test_cancel_subscription_calls_paypal():
    with patch(
        "app.services.paypal_service._PayPalV2HTTP.post",
        return_value={},
    ) as mock_post:
        out = PayPalService.cancel_subscription("I-TESTSUB123", "user requested")

    mock_post.assert_called_once()
    args, _ = mock_post.call_args
    assert args[0] == "/v1/billing/subscriptions/I-TESTSUB123/cancel"
    assert args[1] == {"reason": "user requested"}
    assert out["status"] == "cancelled"


def test_cancel_subscription_raises_not_found():
    with patch(
        "app.services.paypal_service._PayPalV2HTTP.post",
        side_effect=NotFoundException("404"),
    ):
        with pytest.raises(NotFoundException):
            PayPalService.cancel_subscription("I-MISSING")


def test_create_subscription_returns_approval_url():
    fake_response = {
        "id": "I-NEW-SUB",
        "status": "APPROVAL_PENDING",
        "links": [
            {"href": "https://api.paypal.com/...", "rel": "self"},
            {"href": "https://paypal.com/checkoutnow?token=ABC", "rel": "approve"},
        ],
    }
    with patch(
        "app.services.paypal_service._PayPalV2HTTP.post",
        return_value=fake_response,
    ):
        out = PayPalService.create_subscription(
            plan_id="P-PLAN-PLUS-MONTHLY",
            return_url="https://app.example.com/return",
            cancel_url="https://app.example.com/cancel",
        )

    assert out["subscription_id"] == "I-NEW-SUB"
    assert out["approval_url"] == "https://paypal.com/checkoutnow?token=ABC"
    assert out["status"] == "APPROVAL_PENDING"


def test_create_subscription_raises_when_no_approve_link():
    fake_response = {
        "id": "I-NEW-SUB",
        "status": "APPROVAL_PENDING",
        "links": [{"href": "https://api.paypal.com/...", "rel": "self"}],
    }
    with patch(
        "app.services.paypal_service._PayPalV2HTTP.post",
        return_value=fake_response,
    ):
        with pytest.raises(ValidationException):
            PayPalService.create_subscription(
                plan_id="P-PLAN", return_url="x", cancel_url="y"
            )
