"""UX-E1 chore-chart scanner: a photo of the fridge chart (or a list) → proposed
recurring chores. Same Claude-vision-through-LiteLLM pipeline as the calendar
scanner; the parent reviews and the browser creates each chore through the
ordinary template API. Nothing here is persisted — not the image, not the
proposals.
"""
from __future__ import annotations

import base64
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.llm import RECEIPT_MODEL, get_llm_client
from app.core.metrics import record_llm_call
from app.services.budget.receipt_scanner_service import _pdf_first_page_to_png

MAX_PROPOSALS = 40
TITLE_MAX = 200
DESCRIPTION_MAX = 1000
DEFAULT_POINTS = 10

_DAY_WORDS = {
    "mon": 0, "monday": 0, "lun": 0, "lunes": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "mar": 1, "martes": 1,
    "wed": 2, "wednesday": 2, "mie": 2, "miercoles": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "jue": 3, "jueves": 3,
    "fri": 4, "friday": 4, "vie": 4, "viernes": 4,
    "sat": 5, "saturday": 5, "sab": 5, "sabado": 5,
    "sun": 6, "sunday": 6, "dom": 6, "domingo": 6,
}
_DAY_GROUPS = {
    "weekdays": [0, 1, 2, 3, 4], "entre semana": [0, 1, 2, 3, 4],
    "weekends": [5, 6], "weekend": [5, 6], "fin de semana": [5, 6], "fines de semana": [5, 6],
}


@dataclass(frozen=True)
class Member:
    id: UUID
    name: str
    role: str


@dataclass
class ScannedChore:
    title: str
    points: int = DEFAULT_POINTS
    is_bonus: bool = False
    days_of_week: list[int] = field(default_factory=list)
    assignee_names: list[str] = field(default_factory=list)
    assigned_user_ids: list[UUID] = field(default_factory=list)
    unmatched_names: list[str] = field(default_factory=list)
    duplicate_of: Optional[UUID] = None
    description: Optional[str] = None


@dataclass
class ScannedChart:
    doc_type: str = "other"
    confidence: float = 0.0
    chores: list[ScannedChore] = field(default_factory=list)


def fold(text: str) -> str:
    """Lower-case, accents stripped, whitespace collapsed — the comparison form."""
    stripped = "".join(ch for ch in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(ch))
    return " ".join(stripped.lower().split())


def match_members(names: list[str], members: list[Member]) -> tuple[list[UUID], list[str]]:
    """Member ids for the names a chart row carries, in order, plus the names
    that matched nobody. A name matches a member's full name or first name;
    an ambiguous first name (two members share it) matches nobody — never
    assign a chore to the wrong kid."""
    by_full: dict[str, UUID] = {fold(m.name): m.id for m in members}
    first_counts: dict[str, int] = {}
    for m in members:
        first = fold(m.name).split(" ")[0] if fold(m.name) else ""
        first_counts[first] = first_counts.get(first, 0) + 1
    by_first: dict[str, UUID] = {
        fold(m.name).split(" ")[0]: m.id for m in members if first_counts.get(fold(m.name).split(" ")[0]) == 1
    }
    ids: list[UUID] = []
    missing: list[str] = []
    for raw in names or []:
        name = (raw or "").strip() if isinstance(raw, str) else ""
        if not name:
            continue
        key = fold(name)
        hit = by_full.get(key) or by_first.get(key)
        if hit is None:
            if name not in missing:
                missing.append(name)
        elif hit not in ids:
            ids.append(hit)
    return ids, missing


def normalize_days(raw: Any) -> list[int]:
    """0 = Monday … 6 = Sunday, unique and sorted; empty = every day.
    Accepts numbers, day names (en/es, abbreviated) and the groups
    'weekdays' / 'weekends'; anything else is dropped."""
    # The model sometimes answers a bare word ("weekdays") instead of a list.
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: set[int] = set()
    for item in raw:
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)):
            if float(item).is_integer() and 0 <= int(item) <= 6:
                out.add(int(item))
            continue
        if isinstance(item, str):
            key = fold(item)
            if key in _DAY_GROUPS:
                out.update(_DAY_GROUPS[key])
            elif key in _DAY_WORDS:
                out.add(_DAY_WORDS[key])
    return sorted(out)


def clamp_points(raw: Any) -> int:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_POINTS
    return max(0, min(1000, value))


def build_prompt(members: list[Member], lang: str) -> str:
    language = "Spanish" if (lang or "").lower().startswith("es") else "English"
    roster = "\n".join(f"- {m.name} ({m.role})" for m in members) or "- (no members listed)"
    return f"""This image is a family chore chart, a handwritten chore list, or a screenshot of one.
Extract every chore as a recurring task. The family members are:
{roster}

Return ONLY JSON in this shape:
{{
  "doc_type": "chore_chart | list | other",
  "confidence": <0.0-1.0>,
  "chores": [
    {{
      "title": "Feed the dog",
      "points": 10,
      "is_bonus": false,
      "days": ["mon", "wed", "fri"],
      "assignees": ["Diego"],
      "notes": "evenings or null"
    }}
  ]
}}

Rules:
- Write titles in {language}, short and imperative ("Feed the dog").
- points: 5 to 50 by effort (5 tiny, 10 normal, 20 big, 50 a whole afternoon).
- is_bonus: true only when the chart marks the chore optional / extra / bonus.
- days: the days of the week the chore applies to, as "mon".."sun", or "weekdays" / "weekends"; an empty list means every day. Never invent days the chart does not show.
- assignees: the member names EXACTLY as listed above when the chart assigns the chore to someone; empty when it does not.
- Do not invent chores that are not on the image. Return an empty list with confidence 0 if nothing readable is there."""


def parse_chart(response_text: str, members: list[Member], existing_titles: dict[str, UUID]) -> ScannedChart:
    """The model's answer → proposals. `existing_titles` maps fold(title) of
    the family's active chores to their ids, for the duplicate flag."""
    match = re.search(r"\{[\s\S]*\}", response_text or "")
    if not match:
        raise ValidationError("Could not read a chore chart in that image")
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        raise ValidationError("Could not read a chore chart in that image")
    rows = data.get("chores") if isinstance(data, dict) else None
    chores: list[ScannedChore] = []
    for raw in rows if isinstance(rows, list) else []:
        if not isinstance(raw, dict):
            continue
        title = " ".join(str(raw.get("title") or "").split())[:TITLE_MAX]
        if not title:
            continue
        names = raw.get("assignees") if isinstance(raw.get("assignees"), list) else []
        ids, missing = match_members([n for n in names if isinstance(n, str)], members)
        notes = raw.get("notes")
        description = " ".join(str(notes).split())[:DESCRIPTION_MAX] if isinstance(notes, str) and notes.strip() else None
        chores.append(ScannedChore(
            title=title,
            points=clamp_points(raw.get("points")),
            is_bonus=bool(raw.get("is_bonus", False)),
            days_of_week=normalize_days(raw.get("days")),
            assignee_names=[n.strip() for n in names if isinstance(n, str) and n.strip()],
            assigned_user_ids=ids,
            unmatched_names=missing,
            duplicate_of=existing_titles.get(fold(title)),
            description=description,
        ))
        if len(chores) >= MAX_PROPOSALS:
            break
    try:
        confidence = float((data.get("confidence") if isinstance(data, dict) else 0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    doc_type = str((data.get("doc_type") if isinstance(data, dict) else None) or "other")[:32]
    return ScannedChart(doc_type=doc_type, confidence=max(0.0, min(1.0, confidence)), chores=chores)


async def scan_chore_chart(
    image_bytes: bytes, media_type: str, members: list[Member], existing_titles: dict[str, UUID], lang: str,
) -> ScannedChart:
    if not settings.LITELLM_API_KEY:
        raise ValidationError("Chart scanning is not configured. Set LITELLM_API_KEY.")
    if media_type == "application/pdf":
        image_bytes = await run_in_threadpool(_pdf_first_page_to_png, image_bytes)
        media_type = "image/jpeg"
    client = get_llm_client()
    data_uri = f"data:{media_type};base64,{base64.standard_b64encode(image_bytes).decode('utf-8')}"
    prompt = build_prompt(members, lang)
    try:
        record_llm_call()
        completion = await run_in_threadpool(
            lambda: client.chat.completions.create(
                model=RECEIPT_MODEL,
                max_tokens=3072,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
        )
    except Exception as exc:
        raise ValidationError(f"Chart scan via LiteLLM failed: {exc}")
    return parse_chart((completion.choices[0].message.content or "").strip(), members, existing_titles)
