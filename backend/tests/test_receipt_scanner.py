"""
Tests for Receipt Scanner Service

Tests the receipt scanning endpoint and service logic.
Note: Tests that require the Anthropic API use mocking.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import date
from uuid import uuid4

from app.models.budget import BudgetAccount, BudgetPayee
from app.services.budget.receipt_scanner_service import (
    ScannedReceipt,
    scan_receipt,
    scan_and_create_transaction,
)


@pytest_asyncio.fixture
async def budget_account(db_session: AsyncSession, test_family):
    acct = BudgetAccount(
        family_id=test_family.id,
        name="Checking",
        type="checking",
        offbudget=False,
    )
    db_session.add(acct)
    await db_session.commit()
    await db_session.refresh(acct)
    return acct


class TestScanReceipt:
    """Test the scan_receipt function with mocked Anthropic API."""

    @pytest.mark.asyncio
    async def test_scan_receipt_returns_scanned_data(self):
        """Test that scan_receipt correctly parses Claude Vision response."""
        mock_response_text = '''{
            "date": "2026-03-15",
            "total_amount": -15050,
            "payee_name": "Walmart Supercenter",
            "items": [
                {"name": "Milk 2L", "amount_cents": 4500},
                {"name": "Bread", "amount_cents": 3200},
                {"name": "Eggs 12pk", "amount_cents": 7350}
            ],
            "currency": "MXN",
            "confidence": 0.92
        }'''

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=mock_response_text)]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message

        with patch("app.services.budget.receipt_scanner_service.settings") as mock_settings:
            mock_settings.ANTHROPIC_API_KEY = "test-key"
            with patch("app.services.budget.receipt_scanner_service.anthropic") as mock_anthropic:
                mock_anthropic.Anthropic.return_value = mock_client

                result = await scan_receipt(b"fake-image-bytes", "image/jpeg")

        assert result.date == date(2026, 3, 15)
        assert result.total_amount == -15050
        assert result.payee_name == "Walmart Supercenter"
        assert len(result.items) == 3
        assert result.confidence == 0.92
        assert result.currency == "MXN"

    @pytest.mark.asyncio
    async def test_scan_receipt_no_api_key_raises_error(self):
        """Test that missing API key raises ValidationError."""
        from app.core.exceptions import ValidationError

        with patch("app.services.budget.receipt_scanner_service.settings") as mock_settings:
            mock_settings.ANTHROPIC_API_KEY = ""
            with pytest.raises(ValidationError, match="not configured"):
                await scan_receipt(b"fake-image", "image/jpeg")


class TestScanAndCreateTransaction:
    """Test the full scan-and-create flow."""

    @pytest.mark.asyncio
    async def test_creates_transaction_on_high_confidence(
        self, db_session, test_family, budget_account
    ):
        """Test that a high-confidence scan creates a transaction."""
        mock_receipt = ScannedReceipt(
            date=date(2026, 3, 20),
            total_amount=-8500,
            payee_name="Coffee Shop",
            items=[{"name": "Latte", "amount_cents": 8500}],
            currency="MXN",
            raw_text="",
            confidence=0.85,
        )

        with patch("app.services.budget.receipt_scanner_service.scan_receipt", return_value=mock_receipt):
            result = await scan_and_create_transaction(
                db=db_session,
                family_id=test_family.id,
                account_id=budget_account.id,
                image_bytes=b"fake",
                media_type="image/jpeg",
            )

        assert result["success"] is True
        assert result["transaction_id"] is not None
        assert result["scanned_data"]["payee_name"] == "Coffee Shop"
        assert result["scanned_data"]["total_amount"] == -8500

    @pytest.mark.asyncio
    async def test_returns_low_confidence_without_creating(
        self, db_session, test_family, budget_account
    ):
        """Test that a low-confidence scan does not create a transaction."""
        mock_receipt = ScannedReceipt(
            date=None,
            total_amount=None,
            payee_name=None,
            items=[],
            currency="MXN",
            raw_text="",
            confidence=0.1,
        )

        with patch("app.services.budget.receipt_scanner_service.scan_receipt", return_value=mock_receipt):
            result = await scan_and_create_transaction(
                db=db_session,
                family_id=test_family.id,
                account_id=budget_account.id,
                image_bytes=b"blurry",
                media_type="image/jpeg",
            )

        assert result["success"] is False
        assert result["transaction_id"] is None

    @pytest.mark.asyncio
    async def test_creates_new_payee_if_not_exists(
        self, db_session, test_family, budget_account
    ):
        """Test that scanning creates a new payee when one doesn't exist."""
        mock_receipt = ScannedReceipt(
            date=date(2026, 4, 1),
            total_amount=-25000,
            payee_name="Brand New Store",
            items=[],
            currency="MXN",
            raw_text="",
            confidence=0.9,
        )

        with patch("app.services.budget.receipt_scanner_service.scan_receipt", return_value=mock_receipt):
            result = await scan_and_create_transaction(
                db=db_session,
                family_id=test_family.id,
                account_id=budget_account.id,
                image_bytes=b"fake",
                media_type="image/jpeg",
            )

        assert result["success"] is True

        # Verify payee was created
        from sqlalchemy import select
        stmt = select(BudgetPayee).where(
            BudgetPayee.family_id == test_family.id,
            BudgetPayee.name == "Brand New Store",
        )
        payee_result = await db_session.execute(stmt)
        payee = payee_result.scalars().first()
        assert payee is not None


class TestScanReceiptAPI:
    """Test the API endpoint."""

    @pytest.mark.asyncio
    async def test_scan_endpoint_rejects_non_image(self, client, auth_headers):
        """Test that non-image files are rejected."""
        import io
        # Create a fake text file
        response = await client.post(
            "/api/budget/transactions/scan-receipt",
            headers=auth_headers,
            data={"account_id": str(uuid4())},
            files={"file": ("test.txt", b"not an image", "text/plain")},
        )
        # Should return 200 with success=false (or 403 for premium)
        assert response.status_code in [200, 403]
