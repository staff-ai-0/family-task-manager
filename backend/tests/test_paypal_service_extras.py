"""Tests for PayPalService methods added in v1."""
from unittest.mock import patch, MagicMock

import pytest

from app.services.paypal_service import PayPalService


def test_get_subscription_returns_dict():
    fake_agreement = MagicMock()
    fake_agreement.id = "I-TESTSUB123"
    fake_agreement.state = "Active"
    fake_agreement.plan = MagicMock()
    fake_agreement.plan.id = "P-PLAN-PLUS-MONTHLY"
    fake_agreement.agreement_details = MagicMock()
    fake_agreement.agreement_details.next_billing_date = "2026-06-21T00:00:00Z"

    with patch(
        "paypalrestsdk.BillingAgreement.find", return_value=fake_agreement
    ):
        out = PayPalService.get_subscription("I-TESTSUB123")

    assert out["subscription_id"] == "I-TESTSUB123"
    assert out["status"] == "Active"
    assert out["plan_id"] == "P-PLAN-PLUS-MONTHLY"
    assert out["next_billing_at"] == "2026-06-21T00:00:00Z"


def test_cancel_subscription_calls_paypal():
    fake_agreement = MagicMock()
    fake_agreement.cancel.return_value = True

    with patch(
        "paypalrestsdk.BillingAgreement.find", return_value=fake_agreement
    ):
        out = PayPalService.cancel_subscription("I-TESTSUB123", "user requested")

    fake_agreement.cancel.assert_called_once()
    assert out["status"] == "cancelled"
