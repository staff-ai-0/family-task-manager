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
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from openai import OpenAI
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import ValidationError

# Hard ceiling for any single LiteLLM/vision request. A hung or slow provider
# must never block the event loop indefinitely.
LLM_REQUEST_TIMEOUT_SECONDS = 60.0
from app.core.premium import FEATURE_MIN_PLAN, PLAN_ORDER, get_family_plan
from app.models.budget import (
    BudgetAccount,
    BudgetCategorizationRule,
    BudgetPayee,
    BudgetTransaction,
)
from app.schemas.budget import TransactionCreate
from app.services.budget.transaction_service import TransactionService
from app.services.budget.categorization_rule_service import CategorizationRuleService
from app.services.budget.receipt_draft_service import ReceiptDraftService


logger = logging.getLogger(__name__)


# Fallback model alias when no per-family override is stored in Redis.
# settings.RECEIPT_MODEL is the env-configured default (gemini-2.5-flash).
# Alternatives: "qwen-vl", "claude-haiku", "claude-sonnet", "gpt-4o".
RECEIPT_MODEL = settings.RECEIPT_MODEL

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
    items: list  # [{name, amount_cents, ...}]
    currency: str = "MXN"
    raw_text: str = ""
    confidence: float = 0.0
    # v2 fields
    card_last4: Optional[str] = None
    iva_cents: Optional[int] = None


RECEIPT_PROMPT = """Analyze this receipt image and extract the following information. Return ONLY valid JSON, no markdown or explanation.

{
  "date": "YYYY-MM-DD or null if unreadable",
  "total_amount": <total in the receipt's smallest currency unit (cents/centavos), as integer, NEGATIVE for expenses>,
  "iva_cents": <tax/IVA line as positive integer cents, or null if not present>,
  "payee_name": "store/business name or null",
  "card_last4": "4-digit string (last 4 of the card used) or null",
  "currency": "MXN or USD or other ISO code",
  "items": [
    {
      "name": "item description",
      "qty": <number or null>,
      "unit_price_cents": <positive integer cents per unit, or null>,
      "total_cents": <positive integer cents for the line>,
      "brand": "string or null",
      "raw_text": "the original line as printed on the receipt"
    }
  ],
  "confidence": <0.0-1.0 how confident you are in the extraction>
}

Rules:
- total_amount MUST be negative (it's an expense)
- If the receipt shows MXN $150.50, total_amount = -15050
- If the receipt shows $42.99 USD, total_amount = -4299
- card_last4: look for "**1234", "XXXX1234", "terminada en 1234", "Card: ...1234"
- iva_cents: look for "IVA", "Tax", "Impuesto" line; extract as POSITIVE cents
- Per item: extract qty when explicit ("2 x", "2 PZA"), brand when present
- Set confidence based on image clarity and readability
- If you cannot read the receipt at all, set confidence to 0 and all values to null"""


async def _get_family_model(family_id: UUID) -> str:
    """Return per-family model override from Redis, or the global default."""
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            val = await r.get(f"family_settings:{family_id}:receipt_model")
        finally:
            await r.aclose()
        return val or RECEIPT_MODEL
    except Exception:
        return RECEIPT_MODEL


async def scan_receipt(
    image_bytes: bytes, media_type: str, model: Optional[str] = None
) -> ScannedReceipt:
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
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
    )

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    # OpenAI vision content format: data-URI in image_url field.
    # LiteLLM translates this to Anthropic's image content block when
    # forwarding to claude-haiku / claude-sonnet / claude-opus.
    data_uri = f"data:{media_type};base64,{image_b64}"

    active_model = model or RECEIPT_MODEL

    # thinking_config disables Gemini 2.5 Flash's default reasoning mode,
    # which otherwise burns the 4096-token budget before emitting JSON.
    # Only send it for Gemini models — vLLM backends (qwen-vl, etc.) don't
    # understand the parameter and will 422 if it reaches them.
    extra: dict = {}
    if "gemini" in active_model.lower():
        extra = {"thinking_config": {"thinking_budget": 0}}

    # max_tokens sized for JSON output only; 4096 fits ~80 line items.
    # response_format json_object forces a single JSON value, eliminating
    # the "Here is the JSON:" prose-wrapper failure mode.
    try:
        # The OpenAI client is synchronous (blocking I/O). Offload to a worker
        # thread so a slow provider can't stall the async event loop; the
        # client-level timeout above bounds the wait.
        completion = await run_in_threadpool(
            lambda: client.chat.completions.create(
                model=active_model,
                max_tokens=4096,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},
                            {"type": "text", "text": RECEIPT_PROMPT},
                        ],
                    }
                ],
                extra_body=extra if extra else None,
            )
        )
    except Exception as exc:
        # Surface all proxy-side failures (budget exceeded, rate limits,
        # upstream 5xx, credit balance too low) as ValidationError so the
        # caller always sees a clean error response.
        raise ValidationError(f"Receipt scan via LiteLLM failed: {exc}")

    response_text = (completion.choices[0].message.content or "").strip()
    # If the model still returns nothing (Gemini sometimes burns the budget on
    # reasoning and finishes with empty content), surface that explicitly
    # instead of falling into the regex parse path.
    if not response_text:
        raise ValidationError(
            "Vision model returned empty content "
            f"(finish_reason={completion.choices[0].finish_reason!r})."
        )

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
    # Sanity-guard the parsed date: vision models misread receipt dates
    # (e.g. "2087-07-02", "2008-07-29"). Reject anything >30 days in the
    # future or older than ~2 years → fall back to today downstream
    # (`receipt.date or date.today()`), so reports never get garbage months.
    if parsed_date is not None:
        _today = date.today()
        if parsed_date > _today + timedelta(days=30) or parsed_date < _today - timedelta(days=730):
            logger.warning("discarding implausible receipt date %s", parsed_date)
            parsed_date = None

    # Validate card_last4: only accept exactly 4 digit characters
    raw_card = data.get("card_last4")
    parsed_card_last4 = (
        raw_card
        if (isinstance(raw_card, str) and len(raw_card) == 4 and raw_card.isdigit())
        else None
    )

    # Coerce total_amount: vision models sometimes emit a float ("-15050.0")
    # which asyncpg refuses to bind to an INTEGER column ("expected int,
    # got float"). bool is a subclass of int — reject it explicitly so
    # `true` in the JSON doesn't get persisted as 1.
    raw_total = data.get("total_amount")
    if isinstance(raw_total, bool):
        parsed_total = None
    elif isinstance(raw_total, (int, float)):
        parsed_total = int(raw_total)
    else:
        parsed_total = None

    # Same coercion for iva_cents (also INTEGER on the column). Same
    # bool-rejection trick as above.
    raw_iva = data.get("iva_cents")
    if isinstance(raw_iva, bool):
        parsed_iva_cents = None
    elif isinstance(raw_iva, int):
        parsed_iva_cents = raw_iva
    elif isinstance(raw_iva, float):
        parsed_iva_cents = int(raw_iva)
    else:
        parsed_iva_cents = None

    return ScannedReceipt(
        date=parsed_date,
        total_amount=parsed_total,
        payee_name=data.get("payee_name"),
        items=data.get("items", []),
        currency=data.get("currency", "MXN"),
        raw_text=response_text,
        confidence=data.get("confidence", 0.0),
        card_last4=parsed_card_last4,
        iva_cents=parsed_iva_cents,
    )


async def is_feature_enabled(
    db: AsyncSession, family_id: UUID, feature: str,
) -> bool:
    """Cheap boolean check for an optional pipeline feature.

    .. deprecated::
        Inside ``scan_and_create_transaction`` the plan is now resolved
        once per request and reused — see the ``_allows`` closure there.
        This helper is kept for external callers (and per-feature gates
        outside the scanner pipeline) where the single-call overhead is
        acceptable.

    Unlike ``app.core.premium.require_feature``, this never raises and
    does not increment usage. Used for the per-call gates inside the
    scan pipeline — fx_cross_charge, item_trends, a2a_webhook — where a
    "False" result silently disables the feature rather than rejecting
    the request.

    Resolves any user in the family to read the plan via
    ``get_family_plan`` and compares the plan tier to ``FEATURE_MIN_PLAN``.
    Returns False when no user exists for the family (shouldn't happen
    in practice but is the safe default).
    """
    from app.models.user import User

    r = await db.execute(
        select(User).where(User.family_id == family_id).limit(1)
    )
    user = r.scalar_one_or_none()
    if user is None:
        return False
    plan = await get_family_plan(db, user)
    min_plan = FEATURE_MIN_PLAN.get(feature, "free")
    return PLAN_ORDER.get(plan.name, 0) >= PLAN_ORDER.get(min_plan, 0)


async def scan_and_create_transaction(
    db: AsyncSession,
    family_id: UUID,
    account_id: Optional[UUID] = None,
    image_bytes: bytes = b"",
    media_type: str = "image/jpeg",
    user_id: Optional[UUID] = None,
    force: bool = False,
) -> dict:
    """Run the v2 7-stage receipt-scan pipeline.

    Stages:
        (1) Vision extract
        (2) Account auto-detect (card_last4 → last_used → none)
        (3) Drafts routing (low confidence | no accounts | currency mismatch
            on non-Pro plans)
        (4) Duplicate guard (60-second / 1% same-payee window)
        (5) FX cross-charge (for Pro plans when receipt currency != account
            currency)
        (6) Persist transaction + items + auto-categorize header and each
            line item
        (7) Fan-out: shopping auto-check, item-price trends, a2a webhook

    Args:
        db: Async DB session
        family_id: Tenant scope
        account_id: Caller-supplied account override; when None the
            AccountMatchingService picks one
        image_bytes: Raw bytes of the receipt image / rasterized PDF page
        media_type: MIME type
        user_id: Authenticated user — stamped on the persisted transaction
            as ``created_by_id`` and used by ``AccountMatchingService`` for
            the per-user last-used fallback. Optional (defaults to None)
            to keep test callers and the v1 endpoint working.
        force: When True, bypass the duplicate guard. Set by the endpoint
            in response to the 409 dup_warning prompt.

    Returns:
        dict with the v2 response shape (success, transaction_id, items,
        account_match, fx, trends, confidence, shopping_auto_checked,
        warnings, dup_warning, scanned_preview, draft_id, message).
    """
    # Lazy imports — these services live in the same package and would
    # otherwise create an import cycle at module-load time.
    from app.services.budget.account_matching_service import (
        AccountMatchingService,
    )
    from app.services.budget.duplicate_guard_service import (
        DuplicateGuardService,
    )
    from app.services.budget.transaction_item_service import (
        TransactionItemService,
    )
    from app.services.budget.a2a_webhook_service import A2AWebhookService
    from app.services.fx_service import FXService

    # (0) Resolve per-family model preference --------------------------------
    family_model = await _get_family_model(family_id)

    # (1) Vision extract -----------------------------------------------------
    receipt = await scan_receipt(image_bytes, media_type, model=family_model)

    scanned_dict = {
        "date": receipt.date.isoformat() if receipt.date else None,
        "total_amount": receipt.total_amount,
        "payee_name": receipt.payee_name,
        "items": receipt.items,
        "currency": receipt.currency,
        "card_last4": receipt.card_last4,
        "iva_cents": receipt.iva_cents,
    }

    # HITL: low confidence routes to the drafts queue (unchanged from v1)
    if receipt.confidence < 0.3 or receipt.total_amount is None:
        return await _route_to_drafts(
            db, family_id, account_id, image_bytes, receipt, scanned_dict,
            reason="low_confidence",
        )

    # Resolve family plan ONCE for all subsequent feature gates and load
    # the categorization rule set ONCE for header + per-item lookups. The
    # v1 implementation re-queried both per gate / per item, which made
    # an 80-item receipt issue ~165 redundant SELECTs.
    from app.models.user import User as _User
    _user_row = None
    if user_id is not None:
        _user_row = await db.get(_User, user_id)
    if _user_row is None:
        # Fallback: any user in the family (preserves v1-test-path behavior
        # where user_id may be None). Plans are family-scoped so the result
        # is still correct.
        _user_row = (await db.execute(
            select(_User).where(_User.family_id == family_id).limit(1)
        )).scalar_one_or_none()
    _plan = await get_family_plan(db, _user_row) if _user_row else None
    _plan_name = _plan.name if _plan else "free"
    _plan_rank = PLAN_ORDER.get(_plan_name, 0)

    def _allows(feature: str) -> bool:
        """Cheap in-memory tier check using the per-request cached plan."""
        min_plan = FEATURE_MIN_PLAN.get(feature, "free")
        return _plan_rank >= PLAN_ORDER.get(min_plan, 0)

    cached_rules = list((await db.execute(
        select(BudgetCategorizationRule)
        .where(
            BudgetCategorizationRule.family_id == family_id,
            BudgetCategorizationRule.enabled.is_(True),
        )
        .order_by(
            BudgetCategorizationRule.priority.desc(),
            BudgetCategorizationRule.created_at.asc(),
        )
    )).scalars().all())

    # (2) Account auto-detect ------------------------------------------------
    match = await AccountMatchingService.match(
        db, family_id, user_id=user_id,
        card_last4=receipt.card_last4,
        receipt_currency=receipt.currency,
        override_account_id=account_id,
    )
    if match.account_id is None:
        # No accounts at all — drafts queue with no account binding.
        return await _route_to_drafts(
            db, family_id, None, image_bytes, receipt, scanned_dict,
            reason="no_accounts",
        )

    # Drafts gate: non-Pro and currency mismatch routes to drafts queue.
    fx_allowed = _allows("fx_cross_charge")
    if (
        match.matched_account_currency
        and receipt.currency
        and match.matched_account_currency != receipt.currency
        and not fx_allowed
    ):
        return await _route_to_drafts(
            db, family_id, match.account_id, image_bytes, receipt,
            scanned_dict, reason="currency_mismatch",
        )

    # Resolve payee (needed for dup-guard regardless of force flag — we
    # want subsequent force=True retries to find the same payee row)
    payee_id = await _find_or_create_payee(
        db, family_id, receipt.payee_name,
    )

    # (3) FX cross-charge ----------------------------------------------------
    # Compute final_amount BEFORE dup-guard so cross-currency duplicates
    # actually compare like-for-like values. Persisted rows hold post-FX
    # cents — checking against pre-FX would never match.
    fx_info: Optional[dict] = None
    final_amount = receipt.total_amount
    original_amount_cents: Optional[int] = None
    original_currency: Optional[str] = None
    fx_rate: Optional[Decimal] = None
    warnings: list[str] = []
    if (
        match.matched_account_currency
        and receipt.currency
        and match.matched_account_currency != receipt.currency
        and fx_allowed
    ):
        rate = await FXService.get_rate(
            receipt.currency, match.matched_account_currency,
            on_date=receipt.date or date.today(),
        )
        if rate is None:
            # No FX rate available — route to drafts instead of writing the
            # raw foreign-currency cents into a local-currency account
            # (would create a ~17x amount error MXN→USD or similar).
            return await _route_to_drafts(
                db, family_id, match.account_id, image_bytes, receipt,
                scanned_dict, reason="fx_unavailable",
            )
        original_amount_cents = receipt.total_amount
        original_currency = receipt.currency
        fx_rate = rate
        # Convert (signed) — quantize to whole cents with ROUND_HALF_UP
        final_amount = int(
            (Decimal(receipt.total_amount) * rate).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP,
            )
        )
        fx_info = {
            "rate": str(rate),
            "original_amount_cents": original_amount_cents,
            "original_currency": original_currency,
        }

    # (4) Duplicate guard ----------------------------------------------------
    # Compare against the post-FX amount (the value that would actually
    # land in the database). Pre-FX comparison would let cross-currency
    # duplicates through. Pass the receipt date so the guard can do an exact
    # date match (catches bank-import vs re-scan, regardless of when the
    # import ran — the old 60-second window only caught back-to-back scans).
    if not force:
        dup = await DuplicateGuardService.check(
            db, family_id, payee_id=payee_id,
            amount_cents=final_amount,
            transaction_date=receipt.date,
            account_id=match.account_id,
        )
        if dup is not None:
            # Upgrade path: if the existing transaction is missing a receipt
            # image and this scan provides one, silently attach the image to
            # the existing row instead of creating a duplicate or warning.
            if not dup.existing_has_image:
                existing = dup.existing_transaction
                try:
                    from app.services.storage.gcs_receipt_service import GCSReceiptStorage
                    gcs_path = GCSReceiptStorage.upload(
                        family_id=family_id,
                        transaction_id=existing.id,
                        image_bytes=image_bytes,
                        content_type=media_type,
                    )
                    existing.receipt_image_path = gcs_path
                    # Enrich notes with scanned items if existing notes are sparse.
                    richer_notes = _build_notes(receipt.payee_name, receipt.items, receipt.currency)
                    if richer_notes and len(richer_notes) > len(existing.notes or ""):
                        existing.notes = richer_notes
                    await db.commit()
                    await db.refresh(existing)
                except Exception:
                    logger.exception("GCS upgrade failed for txn %s", existing.id)
                    await db.rollback()
                return {
                    "success": True,
                    "transaction_id": str(existing.id),
                    "dup_warning": None,
                    "scanned_preview": scanned_dict,
                    "confidence": receipt.confidence,
                    "items": [i.get("name", "") if isinstance(i, dict) else i for i in (receipt.items or [])],
                    "account_match": {
                        "strategy": match.strategy,
                        "matched_card_last4": match.matched_card_last4,
                    },
                    "fx": fx_info,
                    "trends": [],
                    "shopping_auto_checked": [],
                    "warnings": warnings + ["receipt_attached_to_existing"],
                    "draft_id": None,
                    "message": "Receipt image attached to existing transaction.",
                }
            # Existing has image (or same richness) — warn as before.
            # Do NOT commit — the flushed-but-uncommitted new payee row
            # (if any) will be rolled back when the session closes at the
            # request boundary. A subsequent force=True call will find/
            # reuse this payee idempotently via _find_or_create_payee.
            return {
                "success": False,
                "transaction_id": None,
                "dup_warning": {
                    "existing_transaction_id": str(
                        dup.existing_transaction_id
                    ),
                    "scanned_at": dup.warning.scanned_at.isoformat(),
                    "amount_cents": dup.warning.amount_cents,
                    "payee": receipt.payee_name,
                },
                "scanned_preview": scanned_dict,
                "confidence": receipt.confidence,
                "items": [],
                "account_match": {
                    "strategy": match.strategy,
                    "matched_card_last4": match.matched_card_last4,
                },
                "fx": fx_info,
                "trends": [],
                "shopping_auto_checked": [],
                "warnings": warnings,
                "draft_id": None,
            }

    # (5) Persist transaction ------------------------------------------------
    txn_date = receipt.date or date.today()
    # Month-locking gate: a parent may have closed the month after the
    # receipt date. Route to drafts so the human can re-date or unlock.
    from app.services.budget.month_locking_service import MonthLockingService
    try:
        await MonthLockingService.validate_month_not_closed(
            db, family_id, date(txn_date.year, txn_date.month, 1),
        )
    except ValidationError as exc:
        scanned_dict["locked_month_error"] = str(exc)
        return await _route_to_drafts(
            db, family_id, match.account_id, image_bytes, receipt,
            scanned_dict, reason="locked_month",
        )
    txn = BudgetTransaction(
        family_id=family_id,
        account_id=match.account_id,
        date=txn_date,
        amount=final_amount,
        payee_id=payee_id,
        notes=_build_notes(
            receipt.payee_name, receipt.items, receipt.currency,
        ),
        cleared=False,
        reconciled=False,
        card_last4=receipt.card_last4,
        iva_cents=receipt.iva_cents,
        fx_rate=fx_rate,
        original_amount_cents=original_amount_cents,
        original_currency=original_currency,
        created_by_id=user_id,
    )
    db.add(txn)
    await db.flush()

    # (5b) Persist items ----------------------------------------------------
    items_persisted = await TransactionItemService.bulk_create(
        db, family_id, txn.id, items=receipt.items or [],
    )

    # (6) Auto-categorize (transaction header + each item) ------------------
    # Uses the cached rule list resolved at the top of this function — one
    # SELECT instead of N+1 over the items.
    # Pass the merchant name as `description` too so rules keyed on
    # match_field='description' or 'both' fire the same as v1, which
    # categorized off the BudgetTransaction.notes value (the notes here
    # are built from receipt.payee_name via _build_notes).
    _header_notes_for_match = receipt.payee_name or ""
    header_cat = CategorizationRuleService.match_with_cached_rules(
        cached_rules,
        payee=receipt.payee_name,
        description=_header_notes_for_match,
    )
    # Precedence: explicit rule > transfer detection > learned payee default
    # > AI suggestion. Transfer detection (e.g. "Transferencia a BBVA", card
    # payment, ATM withdrawal) keeps non-spending rows out of the AI path.
    payee_row = await db.get(BudgetPayee, payee_id) if payee_id else None
    if not header_cat:
        from app.services.budget.transfer_detector import resolve_transfer_category_id
        transfer_cat = await resolve_transfer_category_id(
            db, family_id, receipt.payee_name, txn.notes,
        )
        if transfer_cat is not None:
            header_cat = transfer_cat
    if not header_cat and payee_row is not None and payee_row.default_category_id:
        header_cat = payee_row.default_category_id
    if not header_cat:
        from app.services.budget.category_ai_service import CategoryAIService
        try:
            header_cat = await CategoryAIService.suggest(
                db, family_id, receipt.payee_name,
                [i.get("name") for i in (receipt.items or []) if isinstance(i, dict)],
                is_income=final_amount > 0,
            )
        except Exception:
            logger.exception("AI categorization failed for txn %s", txn.id)
    if header_cat:
        txn.category_id = header_cat
        # Learning: remember this category for the payee so future scans and
        # imports inherit it without an AI call (Actual-style payee default).
        if payee_row is not None and not payee_row.default_category_id:
            payee_row.default_category_id = header_cat
    for it in items_persisted:
        it.category_id = CategorizationRuleService.match_with_cached_rules(
            cached_rules,
            payee=receipt.payee_name,
            description=receipt.payee_name,
            item_name=it.name,
        )
    await db.commit()
    await db.refresh(txn)

    # Persist the original image to GCS for audit / replay. Best-effort:
    # an upload failure does NOT roll back the scan — the transaction stands
    # without an image rather than losing the user's work.
    try:
        from app.services.storage.gcs_receipt_service import GCSReceiptStorage
        gcs_path = GCSReceiptStorage.upload(
            family_id=family_id,
            transaction_id=txn.id,
            image_bytes=image_bytes,
            content_type=media_type,
        )
        txn.receipt_image_path = gcs_path
        await db.commit()
    except Exception:
        # Best-effort image persistence: the scan itself was already committed
        # above, so we deliberately do NOT roll back here. The common failure —
        # GCSReceiptStorage.upload() raising before the image-path commit —
        # leaves the session clean (verified: a rollback there instead *expires*
        # the committed ORM objects and the downstream best-effort steps then
        # hit MissingGreenlet on lazy attribute access).
        # Caveat: if the image-path commit on line 806 itself fails at the DB
        # layer, the session could be left needing a rollback and the unguarded
        # post-commit reads (trends, account lookup) would 500. That path is not
        # reproduced/tested; it's an accepted low-risk edge for a best-effort,
        # cosmetic image-path write. Revisit by splitting the upload from the
        # path commit if it ever bites.
        logger.exception("GCS upload skipped for txn %s", txn.id)

    # (7a) Shopping auto-check ----------------------------------------------
    shopping_auto_checked: list[str] = []
    try:
        shopping_auto_checked = await _auto_check_shopping_items(
            db, family_id, [i.get("name", "") for i in (receipt.items or [])]
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "shopping auto-check failed",
        )

    # (7b) Trends per item ---------------------------------------------------
    trends: list[dict] = []
    if items_persisted and _allows("item_trends"):
        seen: set[str] = set()
        for it in items_persisted:
            if it.normalized_name in seen:
                continue
            seen.add(it.normalized_name)
            trend = await TransactionItemService.get_trend(
                db, family_id, normalized_name=it.normalized_name,
            )
            if trend:
                trends.append(trend.model_dump())

    # (7c) A2A webhook enqueue ----------------------------------------------
    if _allows("a2a_webhook"):
        try:
            payload = _build_webhook_payload(
                family_id, txn, items_persisted, receipt.currency,
                payee_name=receipt.payee_name,
            )
            # Enqueue only — DO NOT dispatch inline. The webhook target
            # may be slow (or unreachable) and a 10 s timeout would block
            # the scan response. The retry sweep (cron, runs every 5 min)
            # picks up pending deliveries and dispatches them off the hot
            # path. This keeps the user-facing scan ≤2 s.
            await A2AWebhookService.enqueue(
                db, family_id, txn.id, payload=payload,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "a2a enqueue failed",
            )

    # Build a small `transaction` sub-object so the confirm card on the
    # client can render { payee, amount, currency, account_name, iva }
    # without an extra round-trip. The full TransactionResponse is more
    # than the card needs and would force a Decimal-aware decoder client
    # side.
    matched_account = await db.get(BudgetAccount, match.account_id)
    display_currency = match.matched_account_currency or receipt.currency
    transaction_summary = {
        "id": str(txn.id),
        "account_id": str(match.account_id),
        "account_name": matched_account.name if matched_account else None,
        "amount": int(final_amount),
        "currency": display_currency,
        "payee_name": receipt.payee_name,
        "iva_cents": receipt.iva_cents,
    }

    return {
        "success": True,
        "transaction_id": str(txn.id),
        "transaction": transaction_summary,
        "draft_id": None,
        "items": [
            {
                "id": str(it.id),
                "name": it.name,
                "normalized_name": it.normalized_name,
                "qty": float(it.qty) if it.qty is not None else None,
                "unit_price_cents": it.unit_price_cents,
                "total_cents": it.total_cents,
                "brand": it.brand,
                "category_id": str(it.category_id) if it.category_id else None,
            }
            for it in items_persisted
        ],
        "account_match": {
            "strategy": match.strategy,
            "matched_card_last4": match.matched_card_last4,
        },
        "fx": fx_info,
        "trends": trends,
        "confidence": receipt.confidence,
        "shopping_auto_checked": shopping_auto_checked,
        "warnings": warnings,
        "dup_warning": None,
        "scanned_preview": None,
        # Back-compat with v1 callers that still read `scanned_data`.
        "scanned_data": {
            "date": txn_date.isoformat(),
            "total_amount": receipt.total_amount,
            "payee_name": receipt.payee_name,
            "items": receipt.items,
            "currency": receipt.currency,
        },
        "message": "Transaction created from receipt scan.",
    }


async def _auto_check_shopping_items(
    db: AsyncSession,
    family_id: UUID,
    receipt_item_names: list,
) -> list:
    """Fuzzy-match receipt items against pending shopping items and check them off.

    Match rule: difflib.SequenceMatcher ratio >= 0.72 on lowercased names,
    OR one name appears as a token substring of the other. Each shopping
    item is checked at most once per call.
    """
    from datetime import datetime, timezone
    from difflib import SequenceMatcher
    from app.models.shopping import ShoppingItem, ShoppingList

    receipt_names = [n.strip().lower() for n in receipt_item_names if n and n.strip()]
    if not receipt_names:
        return []

    pending_q = (
        select(ShoppingItem)
        .join(ShoppingList, ShoppingItem.list_id == ShoppingList.id)
        .where(
            ShoppingList.family_id == family_id,
            ShoppingList.is_archived.is_(False),
            ShoppingItem.is_checked.is_(False),
        )
    )
    pending = list((await db.execute(pending_q)).scalars().all())
    if not pending:
        return []

    matched_names: list = []
    now = datetime.now(timezone.utc)
    for item in pending:
        item_name = (item.name or "").strip().lower()
        if not item_name:
            continue
        for r_name in receipt_names:
            ratio = SequenceMatcher(None, item_name, r_name).ratio()
            substr = item_name in r_name or r_name in item_name
            if ratio >= 0.72 or (substr and min(len(item_name), len(r_name)) >= 4):
                item.is_checked = True
                item.checked_at = now
                matched_names.append(item.name)
                break

    if matched_names:
        await db.commit()
    return matched_names


# ---------------------------------------------------------------------------
# Internal helpers for the v2 pipeline.
# These are module-private (single-underscore) and not part of the public
# surface — they exist solely to keep scan_and_create_transaction linear
# and readable. They share the same family-tenant assumptions as the
# caller (every input is already scoped by family_id).
# ---------------------------------------------------------------------------


async def _find_or_create_payee(
    db: AsyncSession, family_id: UUID, payee_name: Optional[str],
) -> Optional[UUID]:
    """Resolve a payee_id for the given name, inserting a new row if needed.

    Returns None when payee_name is None/empty (anonymous receipt). The
    new payee row is flushed (so the FK exists for the transaction insert)
    but NOT committed — the caller's commit / rollback boundary controls
    durability.
    """
    if not payee_name or not payee_name.strip():
        return None
    # Case-insensitive AND trim-insensitive match. Vision models often emit
    # "HEB", " Heb ", "h.e.b." for the same store, and may pad with leading
    # or trailing whitespace; the v1 strict equality created duplicate payee
    # rows on every casing/whitespace variation. Normalize BOTH sides via
    # lower(trim()) so an existing " heb " (legacy) still matches "HEB".
    from sqlalchemy import func as _func
    raw = payee_name.strip()
    normalized = raw.lower()
    stmt = select(BudgetPayee).where(
        BudgetPayee.family_id == family_id,
        _func.lower(_func.trim(BudgetPayee.name)) == normalized,
    )
    payee = (await db.execute(stmt)).scalars().first()
    if payee:
        return payee.id
    # Store the trimmed value so we don't accumulate whitespace variants.
    new_payee = BudgetPayee(family_id=family_id, name=raw)
    db.add(new_payee)
    await db.flush()
    return new_payee.id


async def _route_to_drafts(
    db: AsyncSession,
    family_id: UUID,
    account_id: Optional[UUID],
    image_bytes: bytes,
    receipt: "ScannedReceipt",
    scanned_dict: dict,
    reason: str = "low_confidence",
) -> dict:
    """HITL fallback — persist a BudgetReceiptDraft for human review.

    Used for three cases:
        - low_confidence: vision returned < 0.3 or no total
        - no_accounts: family has no active accounts (cannot place tx)
        - currency_mismatch: receipt currency differs from account
          currency on a plan that does not allow fx_cross_charge

    When account_id is None (no_accounts case), we cannot create a
    draft row because ``BudgetReceiptDraft.account_id`` is non-nullable.
    Returns an error-shape dict in that case instead of crashing.
    """
    if account_id is None:
        # Try to fall back to ANY active, non-deleted account in the family
        # so the draft has somewhere to live. If there is truly no account
        # at all we report the error instead of crashing on a NOT-NULL FK.
        from app.models.budget import BudgetAccount
        stmt = (
            select(BudgetAccount)
            .where(
                BudgetAccount.family_id == family_id,
                BudgetAccount.closed.is_(False),
                BudgetAccount.deleted_at.is_(None),
            )
            .limit(1)
        )
        fallback = (await db.execute(stmt)).scalars().first()
        if fallback is None:
            return {
                "success": False,
                "transaction_id": None,
                "draft_id": None,
                "confidence": receipt.confidence,
                "scanned_data": scanned_dict,
                "message": (
                    f"No budget account available to attach this receipt "
                    f"to ({reason})."
                ),
            }
        account_id = fallback.id

    draft = await ReceiptDraftService.create(
        db=db,
        family_id=family_id,
        account_id=account_id,
        scanned_data=scanned_dict,
        confidence=receipt.confidence,
    )
    # Persist the image so the review queue can render it. Failures here
    # are non-fatal — the draft row still exists for review.
    try:
        os.makedirs(RECEIPT_UPLOADS_DIR, exist_ok=True)
        img_path = os.path.join(RECEIPT_UPLOADS_DIR, f"{draft.id}.jpg")
        with open(img_path, "wb") as f:
            f.write(image_bytes)
        draft.image_url = f"/api/budget/receipt-drafts/{draft.id}/image"
        await db.commit()
    except Exception:
        pass

    # Surface the routing reason in the message but keep the legacy
    # "Low confidence" wording so existing v1 UI strings keep working.
    if reason == "low_confidence":
        message = "Low confidence — saved for review in the receipt queue."
    elif reason == "currency_mismatch":
        message = (
            "currency_mismatch — saved for review in the receipt queue. "
            "Upgrade to Pro for automatic FX conversion."
        )
    else:
        message = f"Routed to drafts queue: {reason}"

    return {
        "success": False,
        "transaction_id": None,
        "draft_id": str(draft.id),
        "confidence": receipt.confidence,
        "scanned_data": scanned_dict,
        "message": message,
    }


def _build_webhook_payload(
    family_id: UUID,
    txn: BudgetTransaction,
    items: list,
    currency: Optional[str],
    payee_name: Optional[str] = None,
) -> dict:
    """Build the a2a webhook payload for a freshly persisted scan.

    Schema: family-budget.receipt.v1 — versioned so external agents can
    pin against a contract. Mirrors the dispatch headers' X-A2A-Schema.
    """
    return {
        "schema": "family-budget.receipt.v1",
        "family_id": str(family_id),
        "transaction_id": str(txn.id),
        "occurred_at": txn.created_at.isoformat() if txn.created_at else None,
        "payee": payee_name,
        "currency": currency,
        "total_cents": int(txn.amount),
        "iva_cents": txn.iva_cents,
        "items": [
            {
                "name": it.name,
                "normalized_name": it.normalized_name,
                "qty": float(it.qty) if it.qty is not None else None,
                "unit_price_cents": it.unit_price_cents,
                "total_cents": it.total_cents,
                "category": (
                    str(it.category_id) if it.category_id else None
                ),
                "brand": it.brand,
            }
            for it in items
        ],
        "location_hint": None,
    }
