"""A BBVA "Comprobante de la operación" screenshot → the transfer's fields.

Same Gemini-through-LiteLLM pipeline as the chore-chart scanner. The model only
READS the slip; kid matching, week mapping and every number that touches money
are decided deterministically in payout_receipt_service. Nothing here is
persisted — not the image, not the fields.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.llm import RECEIPT_MODEL, get_llm_client
from app.core.metrics import record_llm_call
from app.services.budget.receipt_scanner_service import _pdf_first_page_to_png

MAX_TOKENS = 2048
FOLIO_MAX = 40
TEXT_MAX = 200
MAX_AMOUNT_CENTS = 10_000_000  # $100,000 — a weekly allowance is never near this

_WEEK_RE = re.compile(r"semanas?\s+((?:\d{1,2})(?:\s*(?:,|y|e|&|-|a)\s*\d{1,2})*)", re.IGNORECASE)


@dataclass
class ScannedReceipt:
    folio: Optional[str] = None
    receipt_date: Optional[date] = None
    concept: str = ""
    amount_cents: Optional[int] = None
    beneficiary: str = ""
    dest_last4: Optional[str] = None
    confidence: float = 0.0

    @property
    def readable(self) -> bool:
        return bool(self.folio) and self.amount_cents is not None and self.amount_cents > 0


PROMPT = """This image is a Mexican bank transfer receipt (BBVA "Comprobante de la operacion"), possibly from another bank.
Return ONLY JSON in this shape:
{
  "folio": "0011968514",
  "date": "2026-09-04",
  "concept": "semana 36",
  "amount": 250.00,
  "beneficiary": "Ariana Michelle M",
  "dest_last4": "9737",
  "confidence": 0.95
}

Rules:
- folio: the operation reference number ("Folio de la operacion") as a STRING, keeping leading zeros.
- date: ISO yyyy-mm-dd from "Fecha" (Spanish month names: enero..diciembre; "septiembre"/"setiembre" = 09).
- concept: the "Concepto" text exactly as written.
- amount: the "Importe transferido" as a plain number in pesos, no currency symbol or thousands separators.
- beneficiary: "Nombre del beneficiario" exactly as written.
- dest_last4: the last 4 digits of "Cuenta de destino" as a string, or null.
- Never invent a value that is not on the image; use null for anything unreadable. If this is not a transfer receipt, return {"folio": null, "amount": null, "confidence": 0}."""


def week_numbers_from_concept(concept: str) -> list[int]:
    """'semana 36' → [36]; 'semana 36 y 37' → [36, 37]; 'semanas 36, 37 y 38' → [36, 37, 38];
    'semana y oxxo' → []. A '-' or 'a' between two numbers is a range ('36-38')."""
    match = _WEEK_RE.search(concept or "")
    if not match:
        return []
    chunk = match.group(1).lower()
    if re.fullmatch(r"\d{1,2}\s*(?:-|a)\s*\d{1,2}", chunk):
        lo, hi = (int(n) for n in re.findall(r"\d{1,2}", chunk))
        return list(range(lo, hi + 1)) if 1 <= lo <= hi <= 53 and hi - lo < 8 else []
    nums = [int(n) for n in re.findall(r"\d{1,2}", chunk)]
    out: list[int] = []
    for n in nums:
        if 1 <= n <= 53 and n not in out:
            out.append(n)
    return out[:8]


def _amount_cents(raw: Any) -> Optional[int]:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    cents = int((value * 100).to_integral_value())
    return cents if 0 < cents <= MAX_AMOUNT_CENTS else None


def parse_receipt(response_text: str) -> ScannedReceipt:
    match = re.search(r"\{[\s\S]*\}", response_text or "")
    if not match:
        raise ValidationError("Could not read a transfer receipt in that image")
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        raise ValidationError("Could not read a transfer receipt in that image")
    if not isinstance(data, dict):
        raise ValidationError("Could not read a transfer receipt in that image")

    folio_raw = data.get("folio")
    folio = re.sub(r"\s+", "", str(folio_raw))[:FOLIO_MAX] if folio_raw not in (None, "") else None
    when: Optional[date] = None
    if isinstance(data.get("date"), str):
        try:
            when = date.fromisoformat(data["date"].strip()[:10])
        except ValueError:
            when = None
    last4_raw = re.sub(r"\D", "", str(data.get("dest_last4") or ""))
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return ScannedReceipt(
        folio=folio or None,
        receipt_date=when,
        concept=" ".join(str(data.get("concept") or "").split())[:TEXT_MAX],
        amount_cents=_amount_cents(data.get("amount")),
        beneficiary=" ".join(str(data.get("beneficiary") or "").split())[:TEXT_MAX],
        dest_last4=last4_raw[-4:] if len(last4_raw) >= 4 else None,
        confidence=max(0.0, min(1.0, confidence)),
    )


async def scan_receipt_image(image_bytes: bytes, media_type: str) -> ScannedReceipt:
    if not settings.LITELLM_API_KEY:
        raise ValidationError("Receipt scanning is not configured. Set LITELLM_API_KEY.")
    if media_type == "application/pdf":
        image_bytes = await run_in_threadpool(_pdf_first_page_to_png, image_bytes)
        media_type = "image/jpeg"
    client = get_llm_client()
    data_uri = f"data:{media_type};base64,{base64.standard_b64encode(image_bytes).decode('utf-8')}"
    kwargs: dict[str, Any] = {}
    if "gemini" in (RECEIPT_MODEL or "").lower():
        # Gemini 2.5 spends max_tokens on hidden reasoning and can return empty
        # content; reading a slip needs none of it (same fix as the receipt scanner).
        kwargs["extra_body"] = {"thinking_config": {"thinking_budget": 0}}
    try:
        record_llm_call()
        completion = await run_in_threadpool(
            lambda: client.chat.completions.create(
                model=RECEIPT_MODEL,
                max_tokens=MAX_TOKENS,
                response_format={"type": "json_object"},
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": PROMPT},
                    ],
                }],
                **kwargs,
            )
        )
    except Exception as exc:
        raise ValidationError(f"Receipt scan via LiteLLM failed: {exc}")
    choice = completion.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise ValidationError("Receipt scan was cut off; try again")
    return parse_receipt((choice.message.content or "").strip())
