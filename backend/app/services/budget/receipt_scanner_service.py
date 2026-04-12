"""
Receipt Scanner Service

Extracts structured transaction data from receipt photos using a vision
model, routed through the LiteLLM proxy for centralized spend tracking.

The provider under the hood today is Anthropic Claude Haiku (cheapest
current vision-capable model), but because we speak to LiteLLM via the
OpenAI-compatible SDK, switching to GPT-4o-vision, Gemini Flash vision,
or any other vision model is a single-string change in RECEIPT_MODEL.

All requests are authenticated with a scoped LiteLLM virtual key
(settings.LITELLM_API_KEY) that has per-month budget caps configured in
the proxy — if the monthly budget is exceeded, LiteLLM rejects the
request with 429 and the caller gets a ValidationError before any cost
leaks to the upstream provider.
"""

import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openai import OpenAI

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.models.budget import BudgetPayee, BudgetTransaction
from app.schemas.budget import TransactionCreate
from app.services.budget.transaction_service import TransactionService
from app.services.budget.categorization_rule_service import CategorizationRuleService
from app.services.budget.receipt_draft_service import ReceiptDraftService


# LiteLLM model alias. Registered in /mnt/nvme/docker-prod/litellm-proxy/
# litellm_config.yaml. "claude-haiku" is anthropic/claude-haiku-4-5-*,
# the cheapest current model that supports vision input. If a receipt
# is particularly hard to parse, the caller can bump this to
# "claude-sonnet" (anthropic/claude-sonnet-4-6) via a future override.
RECEIPT_MODEL = "claude-haiku"

RECEIPT_UPLOADS_DIR = "/app/uploads/receipt-drafts"


def _build_notes(payee_name: Optional[str], items: list, currency: str = "MXN") -> str:
    """Build a full itemized notes string from scanner output.

    Format:
        Store Name
        • Item A: $12.50 MXN
        • Item B: $5.00 MXN
    """
    lines = []
    if payee_name:
        lines.append(payee_name)
    for item in items:
        name = item.get("name", "").strip()
        if not name:
            continue
        amount_cents = item.get("amount_cents")
        if amount_cents is not None:
            lines.append(f"• {name}: ${abs(amount_cents) / 100:.2f} {currency}")
        else:
            lines.append(f"• {name}")
    return "\n".join(lines) if lines else "Receipt scan"


# DPI for rasterizing PDF pages to PNG before the vision call. 150 is a
# sweet spot for printed receipts: high enough that small text and totals
# are readable, low enough that the resulting PNG fits well under the
# ~5MB vision input budget for Claude Haiku. Tickets térmicos narrow
# receipts end up around 600x1500px at this setting.
PDF_RASTER_DPI = 150


def _pdf_first_page_to_png(pdf_bytes: bytes) -> bytes:
    """Rasterize the first page of a PDF to PNG bytes, in memory.

    Uses PyMuPDF (fitz), which ships as a prebuilt wheel on Linux x86_64
    — no poppler or other system dependency needed. Only the first page
    is rendered; for multi-page receipts the caller is responsible for
    pre-splitting or the user is asked to re-scan. We default to this
    single-page behavior because (a) virtually all supermarket/
    restaurant tickets are one page, (b) iOS Files "Scan Document" often
    creates a single-page PDF per tap even for longer receipts, (c)
    sending a multi-image vision request to every receipt would quadruple
    our token cost for the common case.

    Raises:
        ValidationError: If the bytes are not a valid PDF or the PDF
            has zero pages.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ValidationError(
            "PDF support is not available: pymupdf is not installed"
        ) from exc

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValidationError(f"Could not open PDF: {exc}")

    try:
        if doc.page_count == 0:
            raise ValidationError("PDF has no pages")
        page = doc.load_page(0)
        # fitz renders at 72 DPI by default; scale matrix bumps it up.
        zoom = PDF_RASTER_DPI / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        # Cap to 3000px on the longest side. iOS "Scan Document" PDFs embed
        # full-res camera frames (up to 4032×3024) which rasterize well over
        # Anthropic's 8000px-per-dimension hard limit at 150 DPI. 3000px keeps
        # all text readable while staying safely under the cap.
        max_dim = 3000
        if max(pix.width, pix.height) > max_dim:
            scale = max_dim / max(pix.width, pix.height)
            matrix = fitz.Matrix(zoom * scale, zoom * scale)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
        # JPEG instead of PNG: scanned receipts are photographic (camera
        # noise, gradients, lighting) and compress terribly as PNG
        # (13 MB+ for a typical HEB scan) but well as JPEG (~500KB at
        # quality 85). Anthropic's vision input limit is 5 MB, so JPEG
        # is the only practical choice for scanned documents.
        return pix.tobytes("jpeg", jpg_quality=85)
    finally:
        doc.close()


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
    """Extract transaction data from a receipt image via LiteLLM proxy.

    Uses the OpenAI-compatible Chat Completions endpoint exposed by
    LiteLLM, which translates to the underlying provider's native API
    (Anthropic Messages by default). Centralized spend tracking, model
    switching, and monthly budget enforcement all live in the proxy.

    Args:
        image_bytes: Raw image bytes (JPEG, PNG, WebP, GIF)
        media_type: MIME type (image/jpeg, image/png, etc.)

    Returns:
        ScannedReceipt with extracted data

    Raises:
        ValidationError: If LITELLM_API_KEY is not configured, the proxy
            rejects the request (budget exceeded, model unavailable), or
            the vision model's response can't be parsed into valid JSON.
    """
    if not settings.LITELLM_API_KEY:
        raise ValidationError(
            "Receipt scanning is not configured. Please set LITELLM_API_KEY "
            "to a virtual key issued by the LiteLLM proxy."
        )

    # If the upload is a PDF (typical from iOS Files "Scan Document"),
    # rasterize the first page to PNG in memory before handing off to
    # the vision model. Vision models via LiteLLM/OpenAI-format accept
    # image_url data-URIs only — no direct PDF support over that wire.
    # Normalize the media_type so the downstream data URI is correct.
    if media_type == "application/pdf":
        image_bytes = _pdf_first_page_to_png(image_bytes)
        media_type = "image/jpeg"  # rasterizer outputs JPEG for size

    # OpenAI SDK pointed at LiteLLM's /v1 endpoint. The proxy handles
    # authentication, request translation to the provider's native
    # format, budget enforcement, and spend logging.
    client = OpenAI(
        base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
        api_key=settings.LITELLM_API_KEY,
    )

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    # OpenAI vision content format: data-URI in image_url field.
    # LiteLLM translates this to Anthropic's image content block when
    # forwarding to claude-haiku / claude-sonnet / claude-opus.
    data_uri = f"data:{media_type};base64,{image_b64}"

    try:
        completion = client.chat.completions.create(
            model=RECEIPT_MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": RECEIPT_PROMPT},
                    ],
                }
            ],
        )
    except Exception as exc:
        # Surface all proxy-side failures (budget exceeded, rate limits,
        # upstream 5xx, credit balance too low) as ValidationError so the
        # caller always sees a clean error response.
        raise ValidationError(f"Receipt scan via LiteLLM failed: {exc}")

    response_text = (completion.choices[0].message.content or "").strip()

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

    scanned_data_dict = {
        "date": receipt.date.isoformat() if receipt.date else None,
        "total_amount": receipt.total_amount,
        "payee_name": receipt.payee_name,
        "items": receipt.items,
        "currency": receipt.currency,
    }

    if receipt.confidence < 0.3 or receipt.total_amount is None:
        # Save for human review instead of silently discarding
        draft = await ReceiptDraftService.create(
            db=db,
            family_id=family_id,
            account_id=account_id,
            scanned_data=scanned_data_dict,
            confidence=receipt.confidence,
        )
        # Persist the image so the review queue can display it
        try:
            os.makedirs(RECEIPT_UPLOADS_DIR, exist_ok=True)
            img_path = os.path.join(RECEIPT_UPLOADS_DIR, f"{draft.id}.jpg")
            with open(img_path, "wb") as f:
                f.write(image_bytes)  # already JPEG (rasterized if PDF)
            draft.image_url = f"/api/budget/receipt-drafts/{draft.id}/image"
            await db.commit()
        except Exception:
            pass  # image storage failure is non-fatal — draft still exists
        return {
            "success": False,
            "draft_id": str(draft.id),
            "confidence": receipt.confidence,
            "scanned_data": scanned_data_dict,
            "message": "Low confidence — saved for review in the receipt queue.",
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
        notes=_build_notes(receipt.payee_name, receipt.items, receipt.currency),
        cleared=False,
        reconciled=False,
    )

    transaction = await TransactionService.create(db, family_id, transaction_data)

    return {
        "success": True,
        "draft_id": None,
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
