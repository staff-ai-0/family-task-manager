# UX-E1 — Snap a Chore Chart — Design

**Date:** 2026-10-03
**Status:** design decided in conversation 2026-10-03 (two questions answered by the user, the rest delegated: "go with your picks for this task"); awaiting written-spec review
**Program:** UX/GUI program, sub-project **E1** of E (AI-assisted creation). Program D is complete. E was split 2026-10-03 into E1 snap a chore chart (this), E3 AI-guided family setup, E2 voice input — in that order.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` (row E, pattern 4: "AI removes typing" — the vision pieces exist, the entry points are buried).
**Builds on:** the calendar document scanner (`calendar_scanner_service.py`, `POST /api/calendar/scan-document`, `pages/calendar/scan.astro`): photo → review → confirm, Claude vision through LiteLLM, paid-gated, no persistence on scan.

## Goal

A parent photographs the chore chart on the fridge (or a handwritten list, or a screenshot of one) and gets the family's chores in the app in one go: every row becomes a proposed recurring chore with a title, points, the kids it belongs to and the days of the week; the parent fixes what the AI got wrong, unticks what they do not want, and creates them all with one tap.

**Decisions (user, 2026-10-03):**
- E1 first (snap a chore chart), then E3 guided setup, then E2 voice. (Q1 a)
- A scan produces **recurring chores with who and when** — not just names, and not this week's assignments (the shuffle does that from the chores). (Q2 a)

**Delegated to the designer:**
- **Entry point:** a "📷 Scan a chart" action on the parent chores page (`/parent/tasks`), beside the "+" that opens the new-chore form, plus the same link in that page's empty state. The review lives on its own page, `/parent/tasks/scan` (the calendar scan's shape).
- **One AI call per scan**, same gate, model, limits and file types as the calendar scanner: `require_feature("ai_features")`, `AI_LIMIT`, 8 MB, JPEG/PNG/WebP/GIF/PDF (first page). Free families see the upgrade prompt.
- **The AI never writes.** The scan returns proposals; creation goes through the existing `POST /api/task-templates/` one proposal at a time from the browser (≤ 40 per scan), so every created chore is an ordinary chore with the ordinary validation.
- **Kids are matched by name on the server** (the family's members are given to the model; the result's names are matched case- and accent-insensitively, first name or full name). A row the AI assigns to nobody — or to a name that matches nobody — is created as `AUTO` (the shuffle balances it) unless the parent picks someone in the review.
- **Duplicates are flagged, not blocked:** a proposal whose title matches an existing active chore of the family (case- and accent-insensitive) is shown with "already exists" and unticked by default.
- **Points:** the model suggests 5–50 by effort (the app's own range is 0–1000); the review shows the number editable.
- **Days:** a list of weekdays (0 = Monday … 6 = Sunday); an empty list means every day. A chart that says "weekends" → [5, 6]; "weekdays" → [0–4].
- **Bonus vs mandatory:** the model marks "optional / extra / bonus" rows as bonus tasks; everything else is a mandatory chore.
- **Language:** titles are created in the parent's language; the ES/EN translation stays what it is today for hand-made chores (not translated at scan time).

**Not in E1:** voice input (E2), guided setup (E3), creating this week's assignments, reading rewards or points rules off a chart, editing existing chores from a scan, a "re-scan to update" flow, pictures for non-readers, storing the uploaded image.

## Rules

### Scan

`POST /api/task-templates/scan-chart` — parent only, `ai_features` gated, `AI_LIMIT`, multipart `file`. 415 on another file type, 400 on an empty file, 502 when the model call fails or returns nothing usable (like the calendar scan).

The prompt gives the model: the family's member names (kids and parents; role noted), the parent's language, and asks for JSON:

```json
{
  "doc_type": "chore_chart | list | other",
  "confidence": 0.0,
  "chores": [
    {"title": "Feed the dog", "points": 10, "is_bonus": false,
     "days": [0, 2, 4], "assignees": ["Diego"], "notes": "evenings or null"}
  ]
}
```

The server turns that into `ScanChartResponse { doc_type, confidence, chores: [ScannedChore] }` where `ScannedChore = { title (≤ 200, trimmed), points (clamped 0–1000, default 10), is_bonus, days_of_week (validated 0–6, unique, sorted), assignee_names (as read), assigned_user_ids (matched members), unmatched_names (read but matched nobody), duplicate_of (id of an existing active chore with the same title, or null), description (notes, ≤ 1000, or null) }`. Rows without a title are dropped; more than 40 rows → the first 40.

Nothing is stored by the scan — not the image, not the proposals.

### Review and create

`/parent/tasks/scan` — parent only. Pick a file → "Scanning…" → a list of proposal rows, each with: a checkbox (ticked unless `duplicate_of`), the title (editable), points (editable number), bonus toggle, the members (chips for every participating member — parents labelled — pre-selected from `assigned_user_ids`; nobody selected = "anyone — the app balances it"), the note (editable; it becomes the chore's description the kid reads), the days (seven toggles; none = every day), a line "already exists" when `duplicate_of`, and a line "couldn't match: Pepe" when `unmatched_names`. "Create N chores" posts each ticked row to `POST /api/task-templates/` (title, points, is_bonus, days_of_week or null, `assignment_type` = `FIXED` + `assigned_user_ids` when members are selected else `AUTO`, `interval_days = 1`, description; for a Spanish-speaking parent the same text also goes to `title_es` / `description_es`, as the new-chore form does, so nothing is auto-translated from Spanish as if it were English), one at a time with progress on the button; rows that fail keep the server's message on the row until a later attempt succeeds, successes disappear and are never re-posted; when all are done, "Created N chores" and a link back to `/parent/tasks`.

Low confidence (< 0.3) or zero rows → "I couldn't read a chart in that picture. Try a clearer photo, straight on." No proposals are shown.

### Copy (ES / EN)

- Action: "📷 Escanear tablero" / "📷 Scan a chart". Page title: "Escanear tablero de tareas" / "Scan a chore chart".
- Pick: "Toma una foto del tablero de tareas (o de una lista)" / "Take a photo of your chore chart (or a list)".
- Result heading: "Encontré {n} tareas — revisa y crea" / "Found {n} chores — review and create".
- Anyone: "Cualquiera (la app reparte)" / "Anyone (the app balances it)". Exists: "Ya existe" / "Already exists". Unmatched: "No encontré a: {names}" / "Couldn't match: {names}".
- Button: "Crear {n} tareas" / "Create {n} chores". Done: "Listo: {n} tareas creadas" / "Done: {n} chores created".

## Architecture

**Backend**
- `backend/app/services/chart_scanner_service.py`: `CHART_PROMPT` (built with the member names and language), `scan_chore_chart(image_bytes, media_type, members, lang) -> ScannedChart`, pure helpers `match_members(names, members) -> (ids, unmatched)`, `normalize_days(raw) -> list[int]`, `fold(text)` (lower-case, accents stripped), `find_duplicates(titles, existing)`. Same LiteLLM client (`get_llm_client`, `RECEIPT_MODEL`), PDF rasterization and threadpool offload as the calendar scanner.
- `backend/app/api/routes/task_templates.py`: `POST /scan-chart` (declared before any `/{template_id}` route), reusing `ALLOWED_SCAN_TYPES`, `MAX_SCAN_BYTES`, `read_upload_capped` (move the two constants to `app/core/upload_validation.py` if they live only in `calendar.py`).
- Schemas in `backend/app/schemas/task_template.py`: `ScannedChore`, `ScanChartResponse`.
- `test_ai_gating.py` gains the new endpoint (every LLM call site is listed there).

**Frontend**
- `frontend/src/pages/parent/tasks/scan.astro` (page) + `frontend/src/lib/chartScan.ts` (pure: `proposalRows(resp, members, lang)`, `templateBody(row)`, copy).
- `frontend/src/pages/parent/tasks.astro`: the action beside "+", and the empty-state link.
- Browser calls: `POST /api/task-templates/scan-chart` and `POST /api/task-templates/` — `pages/api/task-templates/[...path].ts` exists (verify in the plan; add the route-file guard test).
- No native dialogs; kit buttons; `hidden` attribute; section tone sky (doing things).

**Docs:** guide 2.3 gets "Scan a chore chart" (EN/ES); `CLAUDE.md` API section one line; the "two scan triggers" rule concerns receipts and is untouched.

## Error handling

- Model failure / unparsable → 502 with a friendly message on the page; nothing created.
- A row failing on create (validation) → stays with the message; the rest proceed.
- Free plan → upgrade prompt, file picker hidden (the calendar scan's pattern); the API gate still enforces.

## Testing

Backend (`tests/test_chart_scanner.py`, `tests/test_scan_chart_api.py`): pure helpers (fold/match: "diego" = "Diego Martínez", first name and full name, two kids sharing a first name → unmatched; days normalization incl. "weekends"; duplicate detection against existing titles); service with `app.core.llm.OpenAI` mocked (parses, clamps points, drops titleless rows, caps at 40, PDF path, no API key → error); route: parent-only, gating (free → 403, in the gating suite), 415/400, 502 on model failure, response shape, duplicate flag against a real template, member matching against real members.

Frontend (vitest): `chartScan.ts` (rows from a response, body for the create call incl. AUTO vs FIXED, days null when empty), source checks for the page (picker, scanning state, create loop, per-row failure stays), the entry action on `/parent/tasks`, route-file guard; existing guards.

## Rollout and production check

Deploy as usual. Demo family only: mariana → "Scan a chart" with a test image (a chore chart rendered to PNG locally and uploaded through the picker) → proposals show the demo kids matched → create 2 → they appear on `/parent/tasks`; delete them afterwards so the demo family's chores stay as seeded. Free-plan behaviour cannot be checked on the demo (paid) family — covered by tests.
