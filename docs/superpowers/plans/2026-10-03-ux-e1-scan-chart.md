# UX-E1 Snap a Chore Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A parent photographs a chore chart (or a list) and gets proposed recurring chores — title, points, kids, days — in a review page; one tap creates the ticked ones through the normal chore API.

**Architecture:** One new vision call (`chart_scanner_service.py`, the calendar scanner's pipeline) behind `POST /api/task-templates/scan-chart` that returns proposals and stores nothing. The server matches kid names to members and flags duplicates; the browser review page (`/parent/tasks/scan`) edits the rows and creates each ticked one with the existing `POST /api/task-templates/`. No new table, no migration.

**Tech Stack:** FastAPI + LiteLLM (Claude vision via `get_llm_client`, `RECEIPT_MODEL`) · Astro 5 + vitest.

**Spec:** `docs/superpowers/specs/2026-10-03-ux-e1-scan-chart-design.md`

## Global Constraints

- The scan is an LLM call site: `await require_feature("ai_features", db, current_user)` before touching the upload, `@limiter.limit(AI_LIMIT)`, and a `free → 403` / `plus → allowed` pair in `tests/test_ai_gating.py`.
- The scan persists nothing (no image, no proposals). Creation only through `POST /api/task-templates/`.
- Family scope: members and duplicate checks use the caller's `family_id` only.
- File rules identical to the calendar scan: `ALLOWED_SCAN_TYPES`, `MAX_SCAN_BYTES = 8 MB`, PDF first page.
- Response limits: ≤ 40 proposals; title ≤ 200 trimmed; points clamped 0–1000 (default 10); days 0–6 unique sorted; description ≤ 1000.
- Name matching: case- and accent-insensitive, first name or full name; an ambiguous first name (two members) is unmatched.
- Frontend: no native dialogs; kit buttons/classes; `hidden` attribute; no emoji in `<h1>`; every browser path has an Astro route file (`/api/task-templates/[...path].ts` exists).
- Local test env as before (`$SP/*` helper scripts targeting this worktree); never run the whole backend suite in one call. Commit trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **The scan writes nothing** — no DB write and no file write on any scan path, including failures (Tasks 1, 2).
2. **A free family** cannot reach the model (403 before the upload is read); a parent of another family cannot see this family's members or chores through the scan (Task 2).
3. **Name matching** never assigns a chore to the wrong kid: ambiguity → unmatched; a parent's name in the chart → matched to the parent only if the chart says so (Task 1).
4. **Create loop** — a row that fails stays with its message; successes do not re-post on a second "Create" click (Task 3).
5. **Model garbage** (non-JSON, wrong types, 200 rows, negative points) never 500s: 502 or clamped (Task 1).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/core/upload_validation.py` | `ALLOWED_SCAN_TYPES`, `MAX_SCAN_BYTES` (moved from `calendar.py`, which imports them back) |
| `backend/app/services/chart_scanner_service.py` (new) | prompt, pure helpers, `scan_chore_chart` |
| `backend/app/schemas/task_template.py`, `backend/app/api/routes/task_templates.py` | `ScannedChore`, `ScanChartResponse`, `POST /scan-chart` |
| `frontend/src/lib/chartScan.ts` (new), `frontend/src/pages/parent/tasks/scan.astro` (new) | review page |
| `frontend/src/pages/parent/tasks.astro` | entry action + empty-state link |
| `docs/USER_GUIDE_{EN,ES}.md`, `CLAUDE.md` | docs |

---

### Task 1: Scanner service (pure helpers + vision call)

**Files:**
- Create: `backend/app/services/chart_scanner_service.py`
- Modify: `backend/app/core/upload_validation.py` (constants), `backend/app/api/routes/calendar.py` (import them)
- Test: `backend/tests/test_chart_scanner.py`

**Interfaces:**
- Produces (`app.services.chart_scanner_service`):
  - `MAX_PROPOSALS = 40`
  - `@dataclass(frozen=True) Member(id: UUID, name: str, role: str)`
  - `fold(text: str) -> str` — lower-case, accents stripped, whitespace collapsed
  - `match_members(names: list[str], members: list[Member]) -> tuple[list[UUID], list[str]]`
  - `normalize_days(raw) -> list[int]`
  - `clamp_points(raw) -> int`
  - `@dataclass ScannedChore(title, points, is_bonus, days_of_week, assignee_names, assigned_user_ids, unmatched_names, duplicate_of, description)`
  - `@dataclass ScannedChart(doc_type, confidence, chores)`
  - `build_prompt(members: list[Member], lang: str) -> str`
  - `parse_chart(response_text: str, members, existing_titles: dict[str, UUID]) -> ScannedChart` (pure; raises `ValidationError` on unparsable)
  - `async scan_chore_chart(image_bytes, media_type, members, existing_titles, lang) -> ScannedChart`
- `app.core.upload_validation.ALLOWED_SCAN_TYPES`, `MAX_SCAN_BYTES`.

- [ ] **Step 1: Write the failing tests**

```python
"""UX-E1 chore-chart scanner: pure helpers and the (mocked) vision call."""
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.services.chart_scanner_service import (
    MAX_PROPOSALS, Member, build_prompt, clamp_points, fold, match_members, normalize_days, parse_chart,
    scan_chore_chart,
)

DIEGO, SOFIA, MARIANA = uuid4(), uuid4(), uuid4()
MEMBERS = [Member(DIEGO, "Diego Martínez", "teen"), Member(SOFIA, "Sofía Martínez", "child"), Member(MARIANA, "Mariana", "parent")]


def _mock_completion(text):
    msg = MagicMock(); msg.content = text
    choice = MagicMock(); choice.message = msg
    completion = MagicMock(); completion.choices = [choice]
    return completion


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
    monkeypatch.setattr(config.settings, "LITELLM_API_BASE", "https://litellm.test")


class TestFold:
    def test_case_accents_and_spaces(self):
        assert fold("  Sofía   MARTÍNEZ ") == "sofia martinez"
        assert fold("Ñoño") == "nono"
        assert fold("") == ""


class TestMatch:
    def test_first_name_or_full_name_any_case_or_accent(self):
        ids, missing = match_members(["diego", "SOFIA MARTINEZ", "Mariana"], MEMBERS)
        assert ids == [DIEGO, SOFIA, MARIANA] and missing == []

    def test_unknown_names_are_reported_not_guessed(self):
        ids, missing = match_members(["Pepe", "Diego"], MEMBERS)
        assert ids == [DIEGO] and missing == ["Pepe"]

    def test_an_ambiguous_first_name_is_unmatched(self):
        twins = MEMBERS + [Member(uuid4(), "Diego López", "child")]
        ids, missing = match_members(["Diego"], twins)
        assert ids == [] and missing == ["Diego"]
        ids, missing = match_members(["Diego López"], twins)
        assert len(ids) == 1 and missing == []

    def test_blank_and_duplicate_names(self):
        ids, missing = match_members(["", "  ", "Diego", "diego"], MEMBERS)
        assert ids == [DIEGO] and missing == []


class TestDays:
    def test_numbers_words_and_ranges(self):
        assert normalize_days([4, 0, 2, 2]) == [0, 2, 4]
        assert normalize_days(["mon", "Wednesday", "fri"]) == [0, 2, 4]
        assert normalize_days(["weekends"]) == [5, 6]
        assert normalize_days(["weekdays"]) == [0, 1, 2, 3, 4]
        assert normalize_days(["sábado", "domingo"]) == [5, 6]

    def test_garbage_is_dropped(self):
        assert normalize_days([7, -1, "nope", None, 3.0]) == [3]
        assert normalize_days(None) == []
        assert normalize_days("daily") == []


class TestPoints:
    @pytest.mark.parametrize("raw,expected", [(10, 10), ("25", 25), (-5, 0), (5000, 1000), (None, 10), ("x", 10), (7.9, 7)])
    def test_clamped_with_a_default(self, raw, expected):
        assert clamp_points(raw) == expected


class TestPrompt:
    def test_names_roles_and_language_are_in_the_prompt(self):
        p = build_prompt(MEMBERS, "es")
        for s in ("Diego Martínez (teen)", "Sofía Martínez (child)", "Mariana (parent)", "Spanish", '"chores"', "weekdays"):
            assert s in p
        assert "English" in build_prompt(MEMBERS, "en")


class TestParse:
    def test_a_chart_becomes_proposals(self):
        existing = {fold("Feed the dog"): uuid4()}
        raw = json.dumps({"doc_type": "chore_chart", "confidence": 0.9, "chores": [
            {"title": " Feed the dog ", "points": 15, "is_bonus": False, "days": ["mon", "wed"], "assignees": ["Diego"], "notes": "evenings"},
            {"title": "Wash car", "points": 500000, "is_bonus": True, "days": [], "assignees": ["Pepe", "sofia"]},
            {"title": "", "points": 5},
            {"points": 5},
        ]})
        out = parse_chart(raw, MEMBERS, existing)
        assert (out.doc_type, out.confidence) == ("chore_chart", 0.9)
        assert len(out.chores) == 2
        a, b = out.chores
        assert (a.title, a.points, a.is_bonus, a.days_of_week, a.assignee_names, a.assigned_user_ids, a.unmatched_names) == (
            "Feed the dog", 15, False, [0, 2], ["Diego"], [DIEGO], [])
        assert a.duplicate_of == existing[fold("Feed the dog")] and a.description == "evenings"
        assert (b.title, b.points, b.is_bonus, b.days_of_week, b.assigned_user_ids, b.unmatched_names, b.duplicate_of, b.description) == (
            "Wash car", 1000, True, [], [SOFIA], ["Pepe"], None, None)

    def test_json_inside_prose_and_a_cap_of_forty(self):
        rows = [{"title": f"Chore {i}", "points": 10} for i in range(60)]
        raw = "Sure! Here is the JSON:\n" + json.dumps({"doc_type": "list", "confidence": 0.5, "chores": rows}) + "\nHope this helps."
        out = parse_chart(raw, MEMBERS, {})
        assert len(out.chores) == MAX_PROPOSALS == 40 and out.chores[0].title == "Chore 0"

    def test_garbage_never_crashes(self):
        for raw in ("", "no json here", "{]", json.dumps({"chores": "nope"}), json.dumps({"chores": [None, 3, "x"]})):
            if raw in ("", "no json here", "{]"):
                with pytest.raises(ValidationError):
                    parse_chart(raw, MEMBERS, {})
            else:
                assert parse_chart(raw, MEMBERS, {}).chores == []

    def test_titles_are_bounded_and_description_too(self):
        raw = json.dumps({"chores": [{"title": "x" * 300, "notes": "y" * 2000, "days": "weekdays"}]})
        c = parse_chart(raw, MEMBERS, {}).chores[0]
        assert len(c.title) == 200 and len(c.description) == 1000 and c.days_of_week == [0, 1, 2, 3, 4] and c.points == 10


class TestScan:
    async def test_calls_the_vision_model_with_the_image_and_the_family(self):
        payload = json.dumps({"doc_type": "chore_chart", "confidence": 0.8, "chores": [{"title": "Make bed", "assignees": ["Sofía"]}]})
        with patch("app.core.llm.OpenAI") as mock_openai:
            client = MagicMock()
            client.chat.completions.create.return_value = _mock_completion(payload)
            mock_openai.return_value = client
            out = await scan_chore_chart(b"\x89PNG...", "image/png", MEMBERS, {}, "es")
        assert out.chores[0].assigned_user_ids == [SOFIA]
        kwargs = client.chat.completions.create.call_args.kwargs
        content = kwargs["messages"][0]["content"]
        assert content[0]["type"] == "image_url" and content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "Sofía Martínez (child)" in content[1]["text"] and "Spanish" in content[1]["text"]

    async def test_model_failure_is_a_validation_error_not_a_crash(self):
        with patch("app.core.llm.OpenAI") as mock_openai:
            client = MagicMock()
            client.chat.completions.create.side_effect = RuntimeError("upstream down")
            mock_openai.return_value = client
            with pytest.raises(ValidationError):
                await scan_chore_chart(b"img", "image/jpeg", MEMBERS, {}, "en")

    async def test_no_api_key_raises(self, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "")
        with pytest.raises(ValidationError):
            await scan_chore_chart(b"img", "image/jpeg", MEMBERS, {}, "en")


def test_scan_constants_live_in_upload_validation():
    from app.core.upload_validation import ALLOWED_SCAN_TYPES, MAX_SCAN_BYTES
    from app.api.routes import calendar
    assert calendar.ALLOWED_SCAN_TYPES is ALLOWED_SCAN_TYPES and calendar.MAX_SCAN_BYTES == MAX_SCAN_BYTES == 8 * 1024 * 1024
    assert {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"} == ALLOWED_SCAN_TYPES
```

- [ ] **Step 2: Run** `pytest tests/test_chart_scanner.py` — Expected: FAIL at import.

- [ ] **Step 3: Implement**

`upload_validation.py` — append:

```python
# Shared by the document scanners (calendar flyers, chore charts): the file
# types Claude vision accepts here, and a hard cap read in chunks.
ALLOWED_SCAN_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}
MAX_SCAN_BYTES = 8 * 1024 * 1024  # 8 MB
```

`calendar.py` — delete its own `ALLOWED_SCAN_TYPES = {...}` and `MAX_SCAN_BYTES = ...` definitions and import both from `app.core.upload_validation` (extend the existing `from app.core.upload_validation import read_upload_capped` line).

`backend/app/services/chart_scanner_service.py`:

```python
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
```

- [ ] **Step 4: Run** `pytest tests/test_chart_scanner.py tests/test_calendar_scanner.py tests/test_calendar_service.py` — PASS. `ruff check app` clean.

- [ ] **Step 5: Mutation checks** — (a) in `match_members` drop the `first_counts == 1` condition (always build `by_first`): `test_an_ambiguous_first_name_is_unmatched` fails. (b) `max(0, min(1000, value))` → `value`: the clamp test fails. (c) remove the `MAX_PROPOSALS` break: the cap test fails. Restore each.

- [ ] **Step 6: Commit** `feat(ux-e1): chore-chart scanner service`

---

### Task 2: Route, schemas, gating

**Files:**
- Modify: `backend/app/schemas/task_template.py`, `backend/app/api/routes/task_templates.py`, `backend/tests/test_ai_gating.py`
- Test: `backend/tests/test_scan_chart_api.py`

**Interfaces:**
- Produces: `POST /api/task-templates/scan-chart` (multipart `file`; parent; `ai_features`; `AI_LIMIT`) → `ScanChartResponse { doc_type: str, confidence: float, chores: list[ScannedChoreOut] }`, `ScannedChoreOut { title, points, is_bonus, days_of_week: list[int], assignee_names: list[str], assigned_user_ids: list[UUID], unmatched_names: list[str], duplicate_of: Optional[UUID], description: Optional[str] }`. 415 wrong type, 400 empty, 413 too big, 502 model failure.

- [ ] **Step 1: Write the failing tests**

```python
"""UX-E1: the scan-chart endpoint — gate, upload rules, family scope, no writes."""
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import func, select

from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole

URL = "/api/task-templates/scan-chart"


def _completion(payload):
    msg = MagicMock(); msg.content = json.dumps(payload)
    choice = MagicMock(); choice.message = msg
    c = MagicMock(); c.choices = [choice]
    return c


def _vision(payload):
    patcher = patch("app.core.llm.OpenAI")
    mock_openai = patcher.start()
    client = MagicMock()
    client.chat.completions.create.return_value = _completion(payload)
    mock_openai.return_value = client
    return patcher, client


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _count_templates(db):
    return (await db.execute(select(func.count()).select_from(TaskTemplate))).scalar()


class TestScan:
    async def test_proposals_are_matched_and_flagged_and_nothing_is_written(
        self, client, db_session, auth_headers, plus_subscription, test_family, test_parent_user, test_child_user, test_teen_user, monkeypatch,
    ):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        db_session.add(TaskTemplate(id=uuid4(), title="Feed the dog", points=10, interval_days=1, assignment_type=AssignmentType.AUTO,
                                    is_bonus=False, is_active=True, family_id=test_family.id))
        await db_session.commit()
        before = await _count_templates(db_session)
        patcher, llm = _vision({"doc_type": "chore_chart", "confidence": 0.9, "chores": [
            {"title": "feed the DOG", "points": 15, "days": ["mon"], "assignees": ["Test Child"]},
            {"title": "Take out trash", "points": 5, "days": ["weekends"], "assignees": ["Test Teen", "Nobody"]},
        ]})
        try:
            r = await client.post(URL, files={"file": ("chart.png", b"\x89PNG fake", "image/png")}, headers=auth_headers)
        finally:
            patcher.stop()
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["doc_type"] == "chore_chart" and body["confidence"] == 0.9 and len(body["chores"]) == 2
        a, b = body["chores"]
        assert a["assigned_user_ids"] == [str(test_child_user.id)] and a["duplicate_of"] is not None and a["days_of_week"] == [0]
        assert b["assigned_user_ids"] == [str(test_teen_user.id)] and b["unmatched_names"] == ["Nobody"] and b["duplicate_of"] is None
        assert b["days_of_week"] == [5, 6]
        assert await _count_templates(db_session) == before                      # the scan writes nothing
        prompt = llm.chat.completions.create.call_args.kwargs["messages"][0]["content"][1]["text"]
        assert "Test Child (child)" in prompt and "Test Parent (parent)" in prompt

    async def test_another_familys_members_and_chores_never_leak_in(
        self, client, db_session, auth_headers, plus_subscription, test_family, monkeypatch,
    ):
        from app.core import config
        from app.models.family import Family
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        stranger = User(email="stranger@test.com", password_hash="x", name="Zoe", role=UserRole.CHILD, family_id=other.id,
                        email_verified=True, points=0)
        db_session.add(stranger)
        db_session.add(TaskTemplate(id=uuid4(), title="Water plants", points=10, interval_days=1, assignment_type=AssignmentType.AUTO,
                                    is_bonus=False, is_active=True, family_id=other.id))
        await db_session.commit()
        patcher, llm = _vision({"confidence": 0.8, "chores": [{"title": "Water plants", "assignees": ["Zoe"]}]})
        try:
            r = await client.post(URL, files={"file": ("c.jpg", b"img", "image/jpeg")}, headers=auth_headers)
        finally:
            patcher.stop()
        c = r.json()["chores"][0]
        assert c["assigned_user_ids"] == [] and c["unmatched_names"] == ["Zoe"] and c["duplicate_of"] is None
        assert "Zoe" not in llm.chat.completions.create.call_args.kwargs["messages"][0]["content"][1]["text"]

    async def test_upload_rules(self, client, auth_headers, plus_subscription, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        assert (await client.post(URL, files={"file": ("c.txt", b"hello", "text/plain")}, headers=auth_headers)).status_code == 415
        assert (await client.post(URL, files={"file": ("c.png", b"", "image/png")}, headers=auth_headers)).status_code == 400

    async def test_model_failure_is_a_502(self, client, auth_headers, plus_subscription, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
        with patch("app.core.llm.OpenAI") as mock_openai:
            c = MagicMock(); c.chat.completions.create.side_effect = RuntimeError("down"); mock_openai.return_value = c
            r = await client.post(URL, files={"file": ("c.png", b"img", "image/png")}, headers=auth_headers)
        assert r.status_code == 502

    async def test_kids_cannot_scan(self, client, test_child_user, plus_subscription):
        r = await client.post(URL, files={"file": ("c.png", b"img", "image/png")}, headers=await _login(client, "child@test.com"))
        assert r.status_code in (401, 403)
```

Add to `tests/test_ai_gating.py` (next to the recipe-import pair):

```python
@pytest.mark.asyncio
async def test_scan_chart_free_403(client: AsyncClient, auth_headers):
    r = await client.post(
        "/api/task-templates/scan-chart",
        files={"file": ("chart.png", b"\x89PNG fake", "image/png")},
        headers=auth_headers,
    )
    _assert_upgrade_required(r)


@pytest.mark.asyncio
async def test_scan_chart_plus_allowed(client: AsyncClient, auth_headers, plus_subscription, monkeypatch):
    from unittest.mock import MagicMock, patch
    from app.core import config
    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
    with patch("app.core.llm.OpenAI") as mock_openai:
        msg = MagicMock(); msg.content = '{"doc_type": "list", "confidence": 0.7, "chores": [{"title": "Make bed"}]}'
        choice = MagicMock(); choice.message = msg
        completion = MagicMock(); completion.choices = [choice]
        c = MagicMock(); c.chat.completions.create.return_value = completion
        mock_openai.return_value = c
        r = await client.post(
            "/api/task-templates/scan-chart",
            files={"file": ("chart.png", b"\x89PNG fake", "image/png")},
            headers=auth_headers,
        )
    assert r.status_code == 200, r.text
    assert r.json()["chores"][0]["title"] == "Make bed"
```

- [ ] **Step 2: Run** `pytest tests/test_scan_chart_api.py tests/test_ai_gating.py -k scan_chart` — Expected: FAIL (404s).

- [ ] **Step 3: Implement**

`schemas/task_template.py` — append:

```python
class ScannedChoreOut(BaseModel):
    """UX-E1: one proposal read off a chore chart. Nothing here is stored —
    the review page creates the ticked ones with TaskTemplateCreate."""
    title: str
    points: int
    is_bonus: bool
    days_of_week: List[int]
    assignee_names: List[str]
    assigned_user_ids: List[UUID]
    unmatched_names: List[str]
    duplicate_of: Optional[UUID] = None
    description: Optional[str] = None


class ScanChartResponse(BaseModel):
    doc_type: str
    confidence: float
    chores: List[ScannedChoreOut]
```

`routes/task_templates.py` — imports: `File, UploadFile` from fastapi; `from app.core.exceptions import ValidationError`; `from app.core.upload_validation import ALLOWED_SCAN_TYPES, MAX_SCAN_BYTES, read_upload_capped`; `from app.services.chart_scanner_service import Member, fold, scan_chore_chart`; `from app.services.family_service import FamilyService`; `from app.models.user import APPROVAL_APPROVED`; `ScanChartResponse, ScannedChoreOut` from the schemas. Insert BEFORE `@router.get("/{template_id}", …)`:

```python
@router.post("/scan-chart", response_model=ScanChartResponse)
@limiter.limit(AI_LIMIT)
async def scan_chart(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """UX-E1: read a chore chart (or list) photo into proposed recurring
    chores. Returns proposals for the parent to review; nothing is stored —
    the browser creates the ticked ones through POST /api/task-templates/."""
    # Plan gate BEFORE the upload is read: this burns LLM tokens.
    await require_feature("ai_features", db, current_user)
    if file.content_type not in ALLOWED_SCAN_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}")
    payload = await read_upload_capped(file, MAX_SCAN_BYTES)
    if not payload:
        raise HTTPException(status_code=400, detail="Empty file")

    family_id = to_uuid_required(current_user.family_id)
    # Participating members only: a deactivated account or a join-code signup
    # still awaiting approval must not be matched (nor shown to the model).
    members = [
        Member(m.id, m.name, str(getattr(m.role, "value", m.role)).lower())
        for m in await FamilyService.get_family_members(db, family_id)
        if m.is_active and m.approval_status == APPROVAL_APPROVED
    ]
    existing = {
        fold(t.title): t.id
        for t in await TaskTemplateService.list_templates(db, family_id, is_active=True)
    }
    try:
        result = await scan_chore_chart(payload, file.content_type, members, existing, current_user.preferred_lang or "es")
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return ScanChartResponse(
        doc_type=result.doc_type,
        confidence=result.confidence,
        chores=[
            ScannedChoreOut(
                title=c.title, points=c.points, is_bonus=c.is_bonus, days_of_week=c.days_of_week,
                assignee_names=c.assignee_names, assigned_user_ids=c.assigned_user_ids,
                unmatched_names=c.unmatched_names, duplicate_of=c.duplicate_of, description=c.description,
            )
            for c in result.chores
        ],
    )
```

(`get_family_members` returns every user of the family, so the filter above is required.)

- [ ] **Step 4: Run** `pytest tests/test_scan_chart_api.py tests/test_ai_gating.py tests/test_task_template_service.py` — PASS. `ruff check app` clean.

- [ ] **Step 5: Mutation check** — remove the `require_feature` line: `test_scan_chart_free_403` fails. Move it after `read_upload_capped`: still passes (gating holds) — keep it first anyway, by spec. Restore.

- [ ] **Step 6: Commit** `feat(ux-e1): scan-chart endpoint (proposals only, paid-gated)`

---

### Task 3: Review page

**Files:**
- Create: `frontend/src/lib/chartScan.ts`, `frontend/src/pages/parent/tasks/scan.astro`
- Test: `frontend/test/chart-scan.test.ts`

**Interfaces:**
- Produces (`lib/chartScan.ts`): `CHART_COPY`, `type Kid = { id: string; name: string }`, `type Row = { key: string; title: string; points: number; isBonus: boolean; days: number[]; kidIds: string[]; unmatched: string[]; duplicate: boolean; description: string | null; checked: boolean }`, `proposalRows(resp: unknown): Row[]`, `templateBody(row: Row): object`, `isUnreadable(resp: unknown): boolean`, `DAY_LABELS`.

- [ ] **Step 1: Write the failing tests**

```ts
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { CHART_COPY, DAY_LABELS, isUnreadable, proposalRows, templateBody } from "../src/lib/chartScan";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");

const resp = {
    doc_type: "chore_chart", confidence: 0.9, chores: [
        { title: "Feed the dog", points: 15, is_bonus: false, days_of_week: [0, 2], assignee_names: ["Diego"], assigned_user_ids: ["d1"], unmatched_names: [], duplicate_of: null, description: "evenings" },
        { title: "Take out trash", points: 5, is_bonus: true, days_of_week: [], assignee_names: ["Pepe"], assigned_user_ids: [], unmatched_names: ["Pepe"], duplicate_of: "t9", description: null },
    ],
};

describe("proposalRows", () => {
    it("maps proposals, unticking duplicates", () => {
        const rows = proposalRows(resp);
        expect(rows).toHaveLength(2);
        expect(rows[0]).toMatchObject({ key: "r0", title: "Feed the dog", points: 15, isBonus: false, days: [0, 2], kidIds: ["d1"], unmatched: [], duplicate: false, description: "evenings", checked: true });
        expect(rows[1]).toMatchObject({ title: "Take out trash", isBonus: true, days: [], kidIds: [], unmatched: ["Pepe"], duplicate: true, description: null, checked: false });
    });
    it("is empty for garbage", () => {
        for (const v of [null, undefined, {}, { chores: "x" }, { chores: [null, 1] }]) expect(proposalRows(v)).toEqual([]);
    });
});

describe("isUnreadable", () => {
    it("low confidence or no rows", () => {
        expect(isUnreadable({ confidence: 0.2, chores: [{ title: "x" }] })).toBe(true);
        expect(isUnreadable({ confidence: 0.9, chores: [] })).toBe(true);
        expect(isUnreadable(resp)).toBe(false);
        expect(isUnreadable(null)).toBe(true);
    });
});

describe("templateBody", () => {
    const row = proposalRows(resp)[0];
    it("FIXED with the kids when any are selected, days as given", () => {
        expect(templateBody(row)).toEqual({
            title: "Feed the dog", points: 15, is_bonus: false, days_of_week: [0, 2], interval_days: 1,
            assignment_type: "fixed", assigned_user_ids: ["d1"], description: "evenings",
        });
    });
    it("AUTO with no kids, null days when every day, no description when empty", () => {
        expect(templateBody({ ...row, kidIds: [], days: [], description: null, title: "  Sweep  " })).toEqual({
            title: "Sweep", points: 15, is_bonus: false, days_of_week: null, interval_days: 1, assignment_type: "auto", assigned_user_ids: null, description: null,
        });
    });
    it("points are whole numbers inside the app's range", () => {
        expect(templateBody({ ...row, points: 1500 }).points).toBe(1000);
        expect(templateBody({ ...row, points: -3 }).points).toBe(0);
        expect(templateBody({ ...row, points: 7.6 }).points).toBe(8);
    });
});

describe("copy", () => {
    it("has both languages and seven day labels", () => {
        expect(DAY_LABELS.es).toHaveLength(7);
        expect(DAY_LABELS.en).toHaveLength(7);
        for (const key of ["title", "pick", "scanning", "found", "anyone", "exists", "unmatched", "create", "done", "unreadable", "failed"] as const) {
            expect(CHART_COPY[key].es.length).toBeGreaterThan(2);
            expect(CHART_COPY[key].en.length).toBeGreaterThan(2);
        }
    });
});

describe("page", () => {
    const page = read("../src/pages/parent/tasks/scan.astro");
    it("is parent-only, paid-gated with the upgrade prompt, sky tone", () => {
        expect(page).toMatch(/if \(user\.role !== "parent"\) return Astro\.redirect\("\/dashboard"\);/);
        expect(page).toMatch(/const aiLocked = await isFreePlan\(token\);/);
        expect(page).toContain("<UpgradePrompt");
        expect(page).toMatch(/tone="sky"/);
    });
    it("scans through the proxied route and creates each ticked row through the ordinary chore API", () => {
        expect(page).toMatch(/fetch\("\/api\/task-templates\/scan-chart"/);
        expect(page).toMatch(/fetch\("\/api\/task-templates\/", \{\s*method: "POST"/);
        expect(page).toMatch(/templateBody\(/);
        expect(page).toMatch(/proposalRows\(/);
        expect(page).toMatch(/isUnreadable\(/);
        expect(existsSync(path("../src/pages/api/task-templates/[...path].ts"))).toBe(true);
    });
    it("a failed row stays with its message and a created row cannot be re-posted", () => {
        expect(page).toMatch(/data-row-error/);
        expect(page).toMatch(/created\.add\(row\.key\)/);
        expect(page).toMatch(/if \(created\.has\(row\.key\)\) continue;/);
    });
    it("uses no native dialog, no emoji in a heading 1, and a hidden attribute for states", () => {
        expect(page).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(page).not.toMatch(/<h1[^>]*>[^<]*[\u{1F300}-\u{1FAFF}]/u);
        expect(page).toMatch(/id="scanning" hidden/);
        expect(page).toMatch(/id="results" hidden/);
    });
});
```

- [ ] **Step 2: Run** `npx vitest run test/chart-scan.test.ts` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

`frontend/src/lib/chartScan.ts`:

```ts
/** UX-E1 snap a chore chart — copy and the pure pieces of the review page. */

export type Lang = "es" | "en";

export const CHART_COPY = {
    title: { es: "Escanear tablero de tareas", en: "Scan a chore chart" },
    subtitle: { es: "Una foto del tablero del refri, una lista escrita o una captura", en: "A photo of the fridge chart, a handwritten list or a screenshot" },
    pick: { es: "Toma una foto del tablero de tareas (o de una lista)", en: "Take a photo of your chore chart (or a list)" },
    scanning: { es: "Leyendo el tablero…", en: "Reading the chart…" },
    found: { es: "Encontré {n} tareas — revisa y crea", en: "Found {n} chores — review and create" },
    anyone: { es: "Cualquiera (la app reparte)", en: "Anyone (the app balances it)" },
    exists: { es: "Ya existe", en: "Already exists" },
    unmatched: { es: "No encontré a: {names}", en: "Couldn't match: {names}" },
    bonus: { es: "Tarea extra", en: "Bonus task" },
    points: { es: "puntos", en: "points" },
    create: { es: "Crear {n} tareas", en: "Create {n} chores" },
    done: { es: "Listo: {n} tareas creadas", en: "Done: {n} chores created" },
    back: { es: "Ver mis tareas", en: "See my chores" },
    unreadable: { es: "No pude leer un tablero en esa foto. Prueba con una foto más clara, de frente.", en: "I couldn't read a chart in that picture. Try a clearer photo, straight on." },
    failed: { es: "No se pudo escanear. Intenta de nuevo.", en: "Could not scan. Try again." },
} as const;

export const DAY_LABELS = {
    es: ["L", "M", "X", "J", "V", "S", "D"],
    en: ["M", "T", "W", "T", "F", "S", "S"],
} as const;

export type Kid = { id: string; name: string };
export type Row = {
    key: string; title: string; points: number; isBonus: boolean; days: number[]; kidIds: string[];
    unmatched: string[]; duplicate: boolean; description: string | null; checked: boolean;
};

const str = (v: unknown) => (typeof v === "string" ? v : "");
const strList = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

export function proposalRows(resp: unknown): Row[] {
    const chores = (resp as { chores?: unknown } | null)?.chores;
    if (!Array.isArray(chores)) return [];
    const rows: Row[] = [];
    chores.forEach((c, i) => {
        if (!c || typeof c !== "object") return;
        const o = c as Record<string, unknown>;
        const title = str(o.title).trim();
        if (!title) return;
        const duplicate = typeof o.duplicate_of === "string" && o.duplicate_of.length > 0;
        rows.push({
            key: `r${i}`,
            title,
            points: typeof o.points === "number" ? o.points : 10,
            isBonus: o.is_bonus === true,
            days: Array.isArray(o.days_of_week) ? o.days_of_week.filter((d): d is number => Number.isInteger(d) && d >= 0 && d <= 6) : [],
            kidIds: strList(o.assigned_user_ids),
            unmatched: strList(o.unmatched_names),
            duplicate,
            description: str(o.description).trim() || null,
            checked: !duplicate,
        });
    });
    return rows;
}

/** Low confidence or nothing found: show one message, no half-results. */
export function isUnreadable(resp: unknown): boolean {
    const r = resp as { confidence?: unknown; chores?: unknown } | null;
    if (!r) return true;
    const conf = typeof r.confidence === "number" ? r.confidence : 0;
    return conf < 0.3 || proposalRows(r).length === 0;
}

/** The body for POST /api/task-templates/ — an ordinary chore. */
export function templateBody(row: Row) {
    const points = Math.max(0, Math.min(1000, Math.round(Number(row.points) || 0)));
    const fixed = row.kidIds.length > 0;
    return {
        title: row.title.trim(),
        points,
        is_bonus: row.isBonus,
        days_of_week: row.days.length ? [...row.days].sort((a, b) => a - b) : null,
        interval_days: 1,
        assignment_type: fixed ? "fixed" : "auto",
        assigned_user_ids: fixed ? row.kidIds : null,
        description: row.description && row.description.trim() ? row.description.trim() : null,
    };
}

export const fill = (s: string, vars: Record<string, string | number>) =>
    s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
```

`frontend/src/pages/parent/tasks/scan.astro` (shape of `calendar/scan.astro`; the review rows are built by the script from `proposalRows`, with `textContent`/`value` for all text — no `innerHTML` with user data):

```astro
---
import PageLayout from "@components/ui/PageLayout.astro";
import UpgradePrompt from "@components/UpgradePrompt.astro";
import { apiFetch } from "../../../lib/api";
import { isFreePlan } from "../../../lib/plan";
import { CHART_COPY } from "../../../lib/chartScan";
import { buttonClass } from "../../../lib/buttonClasses";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");
const lang = (Astro.cookies.get("lang")?.value ?? "es") as "en" | "es";
const { data: user } = await apiFetch<any>("/api/auth/me", { token });
if (!user) {
    Astro.cookies.delete("access_token", { path: "/" });
    return Astro.redirect("/login");
}
if (user.role !== "parent") return Astro.redirect("/dashboard");

// Paid-only (ai_features). Fail-open; the backend enforces.
const aiLocked = await isFreePlan(token);
const { data: members } = await apiFetch<any[]>(`/api/families/${user.family_id}/members`, { token });
const kids = (Array.isArray(members) ? members : [])
    .filter((m: any) => String(m.role).toLowerCase() !== "parent")
    .map((m: any) => ({ id: String(m.id), name: String(m.name) }));
const c = CHART_COPY;
---

<PageLayout
    title={c.title[lang]}
    tone="sky"
    backHref="/parent/tasks"
    backLabel={lang === "es" ? "Volver a tareas" : "Back to chores"}
    role={user.role}
    active="parent"
    lang={lang}
    mainClass="flex-1 px-4 py-6 space-y-4"
>
    <p slot="header-extra" class="text-brand-ink text-sm mt-1">{c.subtitle[lang]}</p>

    {aiLocked && <UpgradePrompt feature="ai_features" planNeeded="Plus" lang={lang} />}

    <div id="scan-root" data-lang={lang} data-kids={JSON.stringify(kids)}>
        <p id="error-box" hidden class="p-3 bg-red-100 border border-red-200 text-red-700 text-sm rounded-xl"></p>

        <label id="picker" hidden={aiLocked}
               class="block bg-brand-cream rounded-2xl border-2 border-dashed border-brand-ink/30 p-10 text-center cursor-pointer hover:border-brand-ink transition-colors">
            <input type="file" id="scan-file" accept="image/jpeg,image/png,image/webp,image/gif,application/pdf" class="hidden" />
            <span class="text-5xl" aria-hidden="true">📷</span>
            <p class="mt-3 text-sm font-semibold text-brand-ink">{c.pick[lang]}</p>
            <p class="text-xs text-brand-ink-soft mt-1">JPG · PNG · WebP · PDF</p>
        </label>

        <div id="scanning" hidden class="bg-brand-cream rounded-2xl p-6 text-center border border-brand-ink/10">
            <div class="inline-block animate-spin h-8 w-8 border-4 border-brand-ink/20 border-t-brand-ink rounded-full"></div>
            <p class="mt-3 text-sm text-brand-ink-soft">{c.scanning[lang]}</p>
        </div>

        <div id="results" hidden class="space-y-3">
            <h2 id="results-heading" class="font-bold text-brand-ink px-1"></h2>
            <div id="rows" class="space-y-3"></div>
            <button type="button" id="create-btn" class={`w-full ${buttonClass("primary", "md")}`}></button>
            <p id="done-box" hidden class="p-3 bg-brand-mint/20 border border-brand-mint text-brand-mint-text text-sm rounded-xl">
                <span id="done-text"></span> · <a href="/parent/tasks" class="font-bold underline">{c.back[lang]}</a>
            </p>
        </div>
    </div>
</PageLayout>

<script>
    import { CHART_COPY, DAY_LABELS, fill, isUnreadable, proposalRows, templateBody, type Kid, type Row } from "../../../lib/chartScan";
    import { showToast } from "../../../lib/toast";

    const root = document.getElementById("scan-root");
    if (root) {
        const lang = root.dataset.lang === "en" ? "en" : "es";
        const kids: Kid[] = (() => { try { return JSON.parse(root.dataset.kids ?? "[]"); } catch { return []; } })();
        const c = CHART_COPY;
        const $ = (id: string) => document.getElementById(id)!;
        const fileInput = $("scan-file") as HTMLInputElement;
        const errorBox = $("error-box"), scanning = $("scanning"), results = $("results"), rowsEl = $("rows");
        const heading = $("results-heading"), createBtn = $("create-btn") as HTMLButtonElement, doneBox = $("done-box"), doneText = $("done-text");
        let rows: Row[] = [];
        const created = new Set<string>();

        const fail = (msg: string) => { errorBox.textContent = msg; errorBox.removeAttribute("hidden"); };
        const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", text = "") => {
            const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n;
        };

        const render = () => {
            rowsEl.replaceChildren();
            const live = rows.filter((r) => !created.has(r.key));
            for (const row of live) {
                const card = el("div", "bg-brand-cream rounded-2xl p-4 border border-brand-ink/10 shadow-[var(--shadow-card)] space-y-2");
                card.dataset.rowKey = row.key;
                const top = el("div", "flex items-start gap-3");
                const check = el("input") as HTMLInputElement; check.type = "checkbox"; check.checked = row.checked; check.className = "mt-2 h-5 w-5 rounded";
                check.addEventListener("change", () => { row.checked = check.checked; syncButton(); });
                const title = el("input") as HTMLInputElement; title.type = "text"; title.value = row.title; title.maxLength = 200;
                title.className = "flex-1 px-2 py-1.5 rounded-lg border border-brand-ink/20 bg-white text-sm text-brand-ink";
                title.addEventListener("input", () => { row.title = title.value; });
                top.append(check, title);
                card.append(top);

                const meta = el("div", "flex flex-wrap items-center gap-2 text-xs text-brand-ink");
                const pts = el("input") as HTMLInputElement; pts.type = "number"; pts.min = "0"; pts.max = "1000"; pts.value = String(row.points);
                pts.className = "w-16 px-2 py-1 rounded-lg border border-brand-ink/20 bg-white text-sm";
                pts.addEventListener("input", () => { row.points = Number(pts.value); });
                meta.append(pts, el("span", "", c.points[lang]));
                const bonusLabel = el("label", "flex items-center gap-1 ml-2");
                const bonus = el("input") as HTMLInputElement; bonus.type = "checkbox"; bonus.checked = row.isBonus;
                bonus.addEventListener("change", () => { row.isBonus = bonus.checked; });
                bonusLabel.append(bonus, el("span", "", c.bonus[lang]));
                meta.append(bonusLabel);
                card.append(meta);

                const kidsRow = el("div", "flex flex-wrap gap-1");
                for (const kid of kids) {
                    const chip = el("button", "", kid.name) as HTMLButtonElement; chip.type = "button";
                    const paint = () => { chip.className = `px-3 py-1 rounded-full text-xs font-semibold border ${row.kidIds.includes(kid.id) ? "bg-brand-sky text-brand-ink border-brand-ink" : "bg-white text-brand-ink border-brand-ink/20"}`; };
                    chip.addEventListener("click", () => { row.kidIds = row.kidIds.includes(kid.id) ? row.kidIds.filter((k) => k !== kid.id) : [...row.kidIds, kid.id]; paint(); anyone.toggleAttribute("hidden", row.kidIds.length > 0); });
                    paint(); kidsRow.append(chip);
                }
                const anyone = el("span", "text-xs text-brand-ink-soft self-center", c.anyone[lang]); anyone.toggleAttribute("hidden", row.kidIds.length > 0);
                kidsRow.append(anyone);
                card.append(kidsRow);

                const daysRow = el("div", "flex gap-1");
                DAY_LABELS[lang].forEach((label, d) => {
                    const b = el("button", "", label) as HTMLButtonElement; b.type = "button"; b.setAttribute("aria-label", `day ${d}`);
                    const paint = () => { b.className = `h-8 w-8 rounded-full text-xs font-bold border ${row.days.includes(d) ? "bg-brand-sky text-brand-ink border-brand-ink" : "bg-white text-brand-ink-soft border-brand-ink/20"}`; };
                    b.addEventListener("click", () => { row.days = row.days.includes(d) ? row.days.filter((x) => x !== d) : [...row.days, d]; paint(); });
                    paint(); daysRow.append(b);
                });
                card.append(daysRow);

                if (row.duplicate) card.append(el("p", "text-xs font-bold text-brand-coral-text", c.exists[lang]));
                if (row.unmatched.length) card.append(el("p", "text-xs text-brand-ink-soft", fill(c.unmatched[lang], { names: row.unmatched.join(", ") })));
                const err = el("p", "text-xs text-red-700"); err.setAttribute("data-row-error", ""); err.setAttribute("hidden", "");
                card.append(err);
                rowsEl.append(card);
            }
            syncButton();
        };

        const syncButton = () => {
            const n = rows.filter((r) => r.checked && !created.has(r.key)).length;
            createBtn.textContent = fill(c.create[lang], { n });
            createBtn.disabled = n === 0;
        };

        fileInput.addEventListener("change", async () => {
            const file = fileInput.files?.[0];
            if (!file) return;
            errorBox.setAttribute("hidden", ""); results.setAttribute("hidden", ""); doneBox.setAttribute("hidden", "");
            scanning.removeAttribute("hidden");
            const fd = new FormData(); fd.append("file", file);
            try {
                const r = await fetch("/api/task-templates/scan-chart", { method: "POST", body: fd, credentials: "same-origin" });
                scanning.setAttribute("hidden", "");
                if (!r.ok) { fail(r.status === 502 ? c.unreadable[lang] : c.failed[lang]); return; }
                const data = await r.json();
                if (isUnreadable(data)) { fail(c.unreadable[lang]); return; }
                rows = proposalRows(data); created.clear();
                heading.textContent = fill(c.found[lang], { n: rows.length });
                render();
                results.removeAttribute("hidden");
            } catch {
                scanning.setAttribute("hidden", "");
                fail(c.failed[lang]);
            } finally {
                fileInput.value = "";
            }
        });

        createBtn.addEventListener("click", async () => {
            createBtn.disabled = true;
            let ok = 0;
            for (const row of rows) {
                if (!row.checked) continue;
                if (created.has(row.key)) continue;
                const card = rowsEl.querySelector<HTMLElement>(`[data-row-key="${row.key}"]`);
                const err = card?.querySelector<HTMLElement>("[data-row-error]");
                try {
                    const r = await fetch("/api/task-templates/", {
                        method: "POST", credentials: "same-origin",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(templateBody(row)),
                    });
                    if (!r.ok) {
                        const body = await r.json().catch(() => null);
                        const detail = body && typeof body.detail === "string" ? body.detail : c.failed[lang];
                        if (err) { err.textContent = detail; err.removeAttribute("hidden"); }
                        continue;
                    }
                    created.add(row.key); ok += 1;
                } catch {
                    if (err) { err.textContent = c.failed[lang]; err.removeAttribute("hidden"); }
                }
            }
            render();
            if (ok) { doneText.textContent = fill(c.done[lang], { n: ok }); doneBox.removeAttribute("hidden"); showToast(fill(c.done[lang], { n: ok }), "success"); }
        });
    }
</script>
```

- [ ] **Step 4: Run** `npx vitest run test/chart-scan.test.ts test/visual-consistency.test.ts test/no-native-dialogs.test.ts test/contrast.test.ts` — PASS. `npm run check` — 0 errors. `npm run build` — OK. (If the visual guard rejects a class used here — e.g. `bg-brand-sky` text contrast — switch the chip fill to the pattern the quest hub card uses.)

- [ ] **Step 5: Mutation checks** — (a) `checked: !duplicate` → `true`: "unticking duplicates" fails. (b) `fixed ? "fixed" : "auto"` → always `"auto"`: the FIXED test fails. (c) `conf < 0.3` → `conf < 0`: the unreadable test fails. Restore each.

- [ ] **Step 6: Commit** `feat(ux-e1): chore-chart review page`

---

### Task 4: Entry points on the parent chores page

**Files:**
- Modify: `frontend/src/pages/parent/tasks.astro`
- Test: `frontend/test/chart-scan-entry.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const page = readFileSync(fileURLToPath(new URL("../src/pages/parent/tasks.astro", import.meta.url)), "utf8");

describe("parent chores page — scan a chart entry", () => {
    it("has a header action beside the + that opens the review page", () => {
        expect(page).toMatch(/<a\s+slot="actions"\s+href="\/parent\/tasks\/scan"[\s\S]*?aria-label=\{lang === "es" \? "Escanear tablero" : "Scan a chart"\}/);
        expect(page.indexOf('href="/parent/tasks/scan"')).toBeLessThan(page.indexOf('id="tcm-trigger"'));
    });
    it("offers the scan in the empty state too", () => {
        const empty = page.slice(page.indexOf("<EmptyState"), page.indexOf("/>", page.indexOf("<EmptyState")));
        expect(empty).toContain('ctaId="tcm-trigger"');
        expect(page).toMatch(/templateList\.length === 0 && \([\s\S]*?href="\/parent\/tasks\/scan"[\s\S]*?Escanear tablero/);
    });
});
```

- [ ] **Step 2: Run** `npx vitest run test/chart-scan-entry.test.ts` — Expected: FAIL.

- [ ] **Step 3: Implement** — in `tasks.astro`, before the existing `<button slot="actions" id="tcm-trigger" …>`:

```astro
    <a
        slot="actions"
        href="/parent/tasks/scan"
        class="press h-10 w-10 rounded-full bg-brand-cream border-2 border-brand-ink shadow-[var(--shadow-card)] text-brand-ink flex items-center justify-center text-lg"
        aria-label={lang === "es" ? "Escanear tablero" : "Scan a chart"}
        title={lang === "es" ? "Escanear tablero" : "Scan a chart"}
    >📷</a>
```

and right after the `<EmptyState … />` inside the `templateList.length === 0 ? (` branch (wrap both in a fragment):

```astro
                        <>
                            <EmptyState … />
                            {templateList.length === 0 && (
                                <p class="text-center text-sm text-brand-ink-soft mt-2">
                                    <a href="/parent/tasks/scan" class="font-semibold text-brand-sky-text hover:underline">
                                        📷 {lang === "es" ? "Escanear tablero del refri" : "Scan the fridge chart"}
                                    </a>
                                </p>
                            )}
                        </>
```

(Keep the existing `EmptyState` props exactly; only wrap.) Check `PageLayout`'s `actions` slot renders several children side by side (read `PageHeader.astro`); if it renders only one, wrap both controls in a `<div slot="actions" class="flex gap-2">`, and adjust the test's first regex to look for the anchor inside that div.

- [ ] **Step 4: Run** `npx vitest run test/chart-scan-entry.test.ts test/visual-consistency.test.ts test/no-native-dialogs.test.ts` and the whole suite — PASS; `npm run check` 0 errors; `npm run build` OK.

- [ ] **Step 5: Commit** `feat(ux-e1): scan-a-chart entry on the parent chores page`

---

### Task 5: Docs

**Files:**
- Modify: `docs/USER_GUIDE_EN.md`, `docs/USER_GUIDE_ES.md`, `CLAUDE.md`

- [ ] **Step 1:** EN guide — after the "Creating a new template" steps (before `### Bilingual translations`):

```markdown
### Scan a chore chart (AI)

Instead of typing every chore, photograph the chart on your fridge, a handwritten list, or a screenshot: on **More → Tasks**, tap **📷** (or "Scan the fridge chart" when the list is empty) and pick the photo.

The app reads it and proposes one recurring chore per row — title, points, which kids (matched to your family members by name) and which days of the week. Review the list: fix a title, change the points, tap a kid's name to add or remove them (nobody selected = the app balances it), tap days to toggle them, untick what you do not want. A chore that already exists is marked and unticked. Then **Create N chores** — each one is created exactly as if you had typed it, and enters the weekly schedule from then on.

> Requires an AI plan (**Plus** or above). The photo is read once and not stored. If the picture cannot be read, you get one message and nothing is created.
```

- [ ] **Step 2:** ES guide — after "Crear una nueva plantilla" (before `### Traducciones bilingues`), unaccented:

```markdown
### Escanear un tablero de tareas (IA)

En vez de escribir cada tarea, toma una foto del tablero del refri, de una lista escrita a mano o de una captura: en **Mas → Tareas**, toca **📷** (o "Escanear tablero del refri" cuando la lista esta vacia) y elige la foto.

La app la lee y propone una tarea recurrente por renglon: titulo, puntos, a que hijos (los reconoce por nombre entre los miembros de tu familia) y que dias de la semana. Revisa la lista: corrige un titulo, cambia los puntos, toca el nombre de un hijo para agregarlo o quitarlo (sin nadie seleccionado, la app reparte), toca los dias para activarlos o no, desmarca lo que no quieras. Una tarea que ya existe aparece marcada como tal y desmarcada. Despues, **Crear N tareas**: cada una se crea exactamente como si la hubieras escrito, y entra al calendario semanal desde ese momento.

> Requiere un plan con IA (**Plus** o superior). La foto se lee una vez y no se guarda. Si no se puede leer, recibes un solo mensaje y no se crea nada.
```

- [ ] **Step 3:** `CLAUDE.md` — in the API structure bullet for `/api/task-templates/`, append one sentence:

```
**Scan a chart** (UX-E1): `POST /api/task-templates/scan-chart` (parent, `ai_features`, `AI_LIMIT`, calendar-scan upload rules now shared in `app/core/upload_validation.py`) reads a chore-chart photo into proposals via `chart_scanner_service.py` — kids matched by name server-side (ambiguous first name → unmatched), duplicates flagged against active titles — and STORES NOTHING; `/parent/tasks/scan` creates each ticked row through the ordinary `POST /api/task-templates/`. Listed in `test_ai_gating.py`.
```

- [ ] **Step 4:** `npx vitest run` + `npm run build` — PASS.

- [ ] **Step 5: Commit** `docs(ux-e1): guides and CLAUDE.md for scanning a chore chart`

---

## After the tasks

1. Final whole-branch review (one fresh reviewer, most capable model) with the Review Focus list; one fix pass, each fix RED→GREEN.
2. Push → PR → CI → merge explicitly → sync main → deploy.
3. Prod check in the demo family only: render a small chore chart to a PNG locally (two chores, "Sofía" and "Diego", some days), upload through the picker as mariana, confirm the kids are matched and the days read, create 2 chores, see them on `/parent/tasks`, then delete them so the demo stays as seeded.
