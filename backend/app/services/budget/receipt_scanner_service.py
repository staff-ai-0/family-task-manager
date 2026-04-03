"""
Receipt Scanner Service

Uses Claude Vision API to extract transaction data from receipt photos.
"""

import base64
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import anthropic

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.models.budget import BudgetPayee, BudgetTransaction
from app.schemas.budget import TransactionCreate
from app.services.budget.transaction_service import TransactionService
from app.services.budget.categorization_rule_service import CategorizationRuleService


@dataclass
class ScannedReceipt:
    """Extracted receipt data from vision analysis."""
    date: Optional[date]
    total_amount: Optional[int]  # in cents
    payee_name: Optional[str]
    items: list  # [{name, amount_cents}]
    currency: str = "MXN"
    raw_text: str = ""
    confidence: float = 0.0


RECEIPT_PROMPT = """Analyze this receipt image and extract the following information. Return ONLY valid JSON, no markdown or explanation.

{
  "date": "YYYY-MM-DD or null if unreadable",
  "total_amount": <total in the receipt's smallest currency unit (cents/centavos), as integer, NEGATIVE for expenses>,
  "payee_name": "store/business name or null",
  "items": [{"name": "item description", "amount_cents": <price in cents as integer>}],
  "currency": "MXN or USD or other ISO code",
  "confidence": <0.0-1.0 how confident you are in the extraction>
}

Rules:
- total_amount MUST be negative (it's an expense)
- If the receipt shows MXN $150.50, total_amount = -15050
- If the receipt shows $42.99 USD, total_amount = -4299
- Extract the business/store name as payee_name
- List individual items if visible
- Set confidence based on image clarity and readability
- If you cannot read the receipt at all, set confidence to 0 and all values to null"""


async def scan_receipt(image_bytes: bytes, media_type: str) -> ScannedReceipt:
    """Extract transaction data from a receipt image using Claude Vision.

    Args:
        image_bytes: Raw image bytes (JPEG, PNG, WebP, GIF)
        media_type: MIME type (image/jpeg, image/png, etc.)

    Returns:
        ScannedReceipt with extracted data

    Raises:
        ValidationError: If API key not configured or image unprocessable
    """
    if not settings.ANTHROPIC_API_KEY:
        raise ValidationError(
            "Receipt scanning is not configured. Please set ANTHROPIC_API_KEY."
        )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": RECEIPT_PROMPT,
                    },
                ],
            }
        ],
    )

    response_text = message.content[0].text.strip()

    # Parse JSON from response (handle potential markdown wrapping)
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if not json_match:
        raise ValidationError("Could not parse receipt data from image")

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        raise ValidationError("Could not parse receipt data from image")

    # Build ScannedReceipt
    parsed_date = None
    if data.get("date"):
        try:
            parsed_date = date.fromisoformat(data["date"])
        except (ValueError, TypeError):
            pass

    return ScannedReceipt(
        date=parsed_date,
        total_amount=data.get("total_amount"),
        payee_name=data.get("payee_name"),
        items=data.get("items", []),
        currency=data.get("currency", "MXN"),
        raw_text=response_text,
        confidence=data.get("confidence", 0.0),
    )


async def scan_and_create_transaction(
    db: AsyncSession,
    family_id: UUID,
    account_id: UUID,
    image_bytes: bytes,
    media_type: str,
) -> dict:
    """Scan a receipt and create a transaction from the extracted data.

    Args:
        db: Database session
        family_id: Family ID
        account_id: Target account
        image_bytes: Receipt image bytes
        media_type: Image MIME type

    Returns:
        Dict with scanned data, created transaction ID, and metadata
    """
    # Scan the receipt
    receipt = await scan_receipt(image_bytes, media_type)

    if receipt.confidence < 0.3 or receipt.total_amount is None:
        return {
            "success": False,
            "confidence": receipt.confidence,
            "scanned_data": {
                "date": receipt.date.isoformat() if receipt.date else None,
                "total_amount": receipt.total_amount,
                "payee_name": receipt.payee_name,
                "items": receipt.items,
                "currency": receipt.currency,
            },
            "message": "Low confidence scan. Please review and enter manually.",
            "transaction_id": None,
        }

    # Find or create payee
    payee_id = None
    if receipt.payee_name:
        stmt = select(BudgetPayee).where(
            BudgetPayee.family_id == family_id,
            BudgetPayee.name == receipt.payee_name,
        )
        result = await db.execute(stmt)
        payee = result.scalars().first()
        if payee:
            payee_id = payee.id
        else:
            new_payee = BudgetPayee(
                family_id=family_id,
                name=receipt.payee_name,
            )
            db.add(new_payee)
            await db.flush()
            payee_id = new_payee.id

    # Auto-categorize via rules
    category_id = await CategorizationRuleService.suggest_category(
        db, family_id,
        payee=receipt.payee_name,
        description=None,
    )

    # Create the transaction
    txn_date = receipt.date or date.today()
    transaction_data = TransactionCreate(
        account_id=account_id,
        date=txn_date,
        amount=receipt.total_amount,
        payee_id=payee_id,
        category_id=category_id,
        notes=f"Receipt scan: {', '.join(i['name'] for i in receipt.items[:3])}" if receipt.items else "Receipt scan",
        cleared=False,
        reconciled=False,
    )

    transaction = await TransactionService.create(db, family_id, transaction_data)

    return {
        "success": True,
        "confidence": receipt.confidence,
        "scanned_data": {
            "date": txn_date.isoformat(),
            "total_amount": receipt.total_amount,
            "payee_name": receipt.payee_name,
            "items": receipt.items,
            "currency": receipt.currency,
        },
        "transaction_id": str(transaction.id),
        "message": "Transaction created from receipt scan.",
    }
