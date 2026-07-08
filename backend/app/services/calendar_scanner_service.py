"""Calendar document scanner (W2.2).

Reuses the LiteLLM/Claude Vision pipeline from receipt_scanner_service to
extract event data from school flyers, sport schedules, invitations, etc.

Returns a list of parsed events for the caller to review/save. We do NOT
auto-persist — calendar events have higher misclassification cost than a
budget transaction (a missed soccer practice is worse than a typo in a
grocery row), so the UX is "scan → review → confirm".
"""

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from fastapi.concurrency import run_in_threadpool
from openai import OpenAI

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.services.budget.receipt_scanner_service import (
    LLM_TIMEOUT,
    RECEIPT_MODEL,
    _pdf_first_page_to_png,
)


CALENDAR_PROMPT = """Analyze this document image (school flyer, sport schedule, invitation, permission slip, etc.) and extract every dated event into a structured list. Return ONLY valid JSON, no markdown or explanation.

{
  "doc_type": "school_flyer | sport_schedule | invitation | permission_slip | other",
  "events": [
    {
      "title": "Soccer practice",
      "start_iso": "2026-05-30T15:00:00",
      "end_iso": "2026-05-30T17:00:00 or null",
      "all_day": false,
      "location": "Main field or null",
      "description": "Short context such as bring water bottle or null"
    }
  ],
  "confidence": <0.0-1.0>
}

Rules:
- start_iso MUST be ISO-8601 in local time WITHOUT timezone offset; the server applies the family timezone.
- If the document gives only a date (no time), set all_day=true and start_iso=YYYY-MM-DDT00:00:00.
- Reject events without a clear date — do not invent dates.
- Set confidence based on legibility and ambiguity.
- Return an empty events list with confidence=0 if nothing dated is readable."""


@dataclass
class ScannedEvent:
    title: str
    start_ts: datetime
    end_ts: Optional[datetime] = None
    all_day: bool = False
    location: Optional[str] = None
    description: Optional[str] = None


@dataclass
class ScannedCalendarDoc:
    doc_type: str = "other"
    events: List[ScannedEvent] = field(default_factory=list)
    confidence: float = 0.0
    raw_text: str = ""


def _parse_iso_local(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def scan_calendar_document(
    image_bytes: bytes, media_type: str
) -> ScannedCalendarDoc:
    if not settings.LITELLM_API_KEY:
        raise ValidationError(
            "Calendar scanning is not configured. Set LITELLM_API_KEY."
        )

    if media_type == "application/pdf":
        # CPU-bound PyMuPDF rasterization — keep it off the event loop.
        image_bytes = await run_in_threadpool(_pdf_first_page_to_png, image_bytes)
        media_type = "image/jpeg"

    client = OpenAI(
        base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
        api_key=settings.LITELLM_API_KEY,
        timeout=LLM_TIMEOUT,  # connect fails fast; read capped at 60s
    )

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:{media_type};base64,{image_b64}"

    try:
        # Sync OpenAI client (blocking I/O) — offload to a worker thread so a
        # slow provider can't stall the async event loop.
        completion = await run_in_threadpool(
            lambda: client.chat.completions.create(
                model=RECEIPT_MODEL,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},
                            {"type": "text", "text": CALENDAR_PROMPT},
                        ],
                    }
                ],
            )
        )
    except Exception as exc:
        raise ValidationError(f"Calendar scan via LiteLLM failed: {exc}")

    response_text = (completion.choices[0].message.content or "").strip()
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if not json_match:
        raise ValidationError("Could not parse calendar data from image")
    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        raise ValidationError("Could not parse calendar data from image")

    events: List[ScannedEvent] = []
    for raw in data.get("events", []) or []:
        start = _parse_iso_local(raw.get("start_iso"))
        if not start or not raw.get("title"):
            continue
        events.append(
            ScannedEvent(
                title=str(raw["title"])[:200],
                start_ts=start,
                end_ts=_parse_iso_local(raw.get("end_iso")),
                all_day=bool(raw.get("all_day", False)),
                location=(raw.get("location") or None),
                description=(raw.get("description") or None),
            )
        )

    return ScannedCalendarDoc(
        doc_type=str(data.get("doc_type", "other"))[:32],
        events=events,
        confidence=float(data.get("confidence", 0.0) or 0.0),
        raw_text=response_text,
    )
