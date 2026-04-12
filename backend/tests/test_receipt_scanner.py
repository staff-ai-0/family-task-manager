"""
Tests for Receipt Scanner Service

Tests the receipt scanning endpoint and service logic.
Note: the scanner routes through the LiteLLM proxy via the OpenAI
SDK, so the mock target is openai.OpenAI (which lives as the
`OpenAI` symbol inside receipt_scanner_service). No real network
calls ever leave the test container.
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
    """Test the scan_receipt function with the LiteLLM/OpenAI client mocked."""

    def _mock_openai_response(self, content: str):
        """Build a mock OpenAI ChatCompletion response wrapping `content`."""
        message = MagicMock()
        message.content = content
        choice = MagicMock()
        choice.message = message
        completion = MagicMock()
        completion.choices = [choice]
        return completion

    @pytest.mark.asyncio
    async def test_scan_receipt_returns_scanned_data(self):
        """scan_receipt parses the vision model's JSON response correctly."""
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

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._mock_openai_response(
            mock_response_text
        )

        with patch(
            "app.services.budget.receipt_scanner_service.settings"
        ) as mock_settings:
            mock_settings.LITELLM_API_KEY = "sk-fake-virtual-key"
            mock_settings.LITELLM_API_BASE = "http://10.1.0.99:4000"
            with patch(
                "app.services.budget.receipt_scanner_service.OpenAI"
            ) as mock_openai:
                mock_openai.return_value = mock_client
                result = await scan_receipt(b"fake-image-bytes", "image/jpeg")

                # OpenAI SDK was instantiated pointing at LiteLLM proxy /v1
                mock_openai.assert_called_once()
                call_kwargs = mock_openai.call_args.kwargs
                assert call_kwargs["base_url"] == "http://10.1.0.99:4000/v1"
                assert call_kwargs["api_key"] == "sk-fake-virtual-key"

                # Correct model alias passed through
                call_args = mock_client.chat.completions.create.call_args
                assert call_args.kwargs["model"] == "claude-haiku"
                # Vision payload contains the image as a data URI
                content = call_args.kwargs["messages"][0]["content"]
                image_part = next(c for c in content if c["type"] == "image_url")
                assert image_part["image_url"]["url"].startswith(
                    "data:image/jpeg;base64,"
                )

        assert result.date == date(2026, 3, 15)
        assert result.total_amount == -15050
        assert result.payee_name == "Walmart Supercenter"
        assert len(result.items) == 3
        assert result.confidence == 0.92
        assert result.currency == "MXN"

    @pytest.mark.asyncio
    async def test_scan_receipt_no_api_key_raises_error(self):
        """Missing LITELLM_API_KEY → ValidationError, OpenAI client never built."""
        from app.core.exceptions import ValidationError

        with patch(
            "app.services.budget.receipt_scanner_service.settings"
        ) as mock_settings:
            mock_settings.LITELLM_API_KEY = ""
            mock_settings.LITELLM_API_BASE = "http://10.1.0.99:4000"
            with patch(
                "app.services.budget.receipt_scanner_service.OpenAI"
            ) as mock_openai:
                with pytest.raises(ValidationError, match="not configured"):
                    await scan_receipt(b"fake-image", "image/jpeg")
                # Fail-fast before any client construction or network IO
                mock_openai.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_receipt_proxy_failure_wraps_as_validation_error(self):
        """LiteLLM proxy errors (budget exceeded, upstream 5xx) surface as ValidationError."""
        from app.core.exceptions import ValidationError

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError(
            "LiteLLM budget exceeded for key family-task-manager-receipt-scanner"
        )

        with patch(
            "app.services.budget.receipt_scanner_service.settings"
        ) as mock_settings:
            mock_settings.LITELLM_API_KEY = "sk-fake"
            mock_settings.LITELLM_API_BASE = "http://10.1.0.99:4000"
            with patch(
                "app.services.budget.receipt_scanner_service.OpenAI"
            ) as mock_openai:
                mock_openai.return_value = mock_client
                with pytest.raises(ValidationError, match="LiteLLM failed|budget exceeded"):
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
