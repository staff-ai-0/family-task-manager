# UX-E3 — AI-guided family setup

**Date:** 2026-10-04 · **Program:** E (AI-assisted creation), second piece after E1 (scan a chore chart) · **Branch:** `feat/ux-e3-guided-setup`

## 1. Intent

A parent who has just registered lands on an empty hub: no chores, no rewards, three blank modules and a list of starter packs to browse. E3 turns "who is in your family and what matters to you" into a tailored first set — chores per kid, rewards, a few cash gigs — that the parent reviews and creates in one go, in about two minutes, and can then refine in a Jarvis chat.

Success: a new parent reaches "first chore created + first reward created" in under three minutes without visiting Tasks, Rewards or Starter packs, on the free plan as well as on a paid one.

Who it is for: parents, on the first days of a family. It is also usable later (a family that added a kid, a parent who skipped setup), because it only proposes — nothing is created until the parent presses Create.

## 2. Decisions taken in brainstorming

| # | Decision |
|---|----------|
| Q1 | Hybrid: a short fixed wizard collects the answers, AI drafts the set, a review page creates it, Jarvis is the refinement hand-off. Not a pure Jarvis chat (question flow would drift; free plan has no AI) and not a pure wizard (no "magic", no refinement). |
| Q2 | Wizard → one draft call → review page (E1 pattern: proposals, ticked rows, ordinary create endpoints, nothing stored until Create) → "Refine with Jarvis" prefilled chat. On the free plan the draft is deterministic (starter packs filtered by the answers) and the Jarvis button is hidden. |
| Q3 | Kids are answers (name + age band), matched to members who already joined. A kid who has not joined can get an account from the review step through the existing parent-only `POST /api/auth/register` (name + email + password), or be left for later: then that kid's chores are created as AUTO rotation (shared among participating members) and the review step shows the join code. Parent-created kid profiles without email (PIN-only) stay a separate candidate project (E4). |

## 3. User flow

One parent-only page, `/parent/setup`, section tone **sky** (doing things). Wizard state lives in memory; nothing persists until Create. Four steps in one page (the step is a `data-step` attribute, back/next buttons, a 4-dot progress row with `aria-current`).

### Step 1 — Kids
- One row per kid: name (text, ≤ 60 chars) + age band chips `3-5` / `6-8` / `9-12` / `13+` (the four `AGE_BANDS` of the starter packs).
- Prefilled with the family's active, approved CHILD/TEEN members: name locked, `member_id` kept, band preselected from `birthdate` when set (age today → band; ≥ 13 → `13+`), else `6-8` for CHILD and `13+` for TEEN. The parent can change the band.
- "+ Add a kid" appends an empty row (name + band, `member_id = null`). Rows added by the parent can be removed; member rows can be unticked ("skip this kid") but not removed.
- Limits: 1–10 kids in the request (`NAMES_MAX = 10`, same as E1). Next is disabled while no row is complete (name non-empty + band chosen).
- Footer link: "Prefer to browse ready-made packs?" → `/parent/starter-packs` (the page stays as it is).

### Step 2 — What matters
- Multi-select chips, 0–6 of: `routine` (mornings & bedtime), `school` (homework & reading), `home` (tidying & cleaning), `kitchen` (meals & table), `pets`, `self_care` (hygiene).
- Optional note, ≤ 300 chars: "Anything else we should know?" (used by the AI draft only; ignored on the pack path).

### Step 3 — Rewards & cash
- Reward style chips, multi-select, 0–5 of the reward categories the app sells as privileges: `screen_time`, `treats`, `activities`, `privileges`, `toys` (never `money`: cash only comes from the gig board).
- Toggle "A cash gig board for extra jobs?" default ON. OFF means: no gig proposals, and on Create the family's `enabled_modules` drops `gigs` (see §6.4).

Pressing "Build my plan" on step 3 posts the draft request (§5) and moves to step 4. While waiting: a skeleton with "Building your family's plan…" (AI path can take up to the read timeout; the pack path is instant).

### Step 4 — Review
- Banner when `source = "pack"` and the family has AI: "AI was not available; here is a starter set for your answers." (`ai_failed = true`). On the free plan no banner (the pack set is the product, not a fallback).
- **Per kid** a card: the kid's name + band, then chore rows: checkbox (ticked unless `duplicate_of`), title (editable, ≤ 200), points (editable, 0–1000), day chips Mon–Sun (editable; none = every day), "Bonus" tag when `is_bonus`. A duplicate row shows "Already exists: <title>" and starts unticked.
- **Kid not joined yet** (`member_id = null`) — the card header carries two things:
  1. The join code (fetched server-side from `GET /api/families/join-code/current`; when null, a "Generate code" button that calls `POST /api/families/join-code/generate`, same as the members page) with the sentence "Share this code; Sofía picks *Child* when she signs up."
  2. A disclosure "Create her account now": email + password (≥ 8) → `POST /api/auth/register` with `{name, email, password, role}` where role = `teen` for band `13+`, else `child`. On 201 the card switches to "joined" (uses the returned id, chores become FIXED to it); on error the message stays on the mini-form (409/400 detail shown via `errorDetail`). Optional — Create works without it.
  Copy under the header when still unjoined: "Until Sofía joins, her chores go into the shared rotation. Assign them from Tasks once she is in."
- **Rewards** section: rows with checkbox, title, points cost (editable, 1–10000), category label. Duplicates as above.
- **Gigs** section (only when cash ON): rows with checkbox, title, cash amount ($ MXN, editable, > 0), difficulty label.
- "Create" button (primary) with the count of ticked rows. Disabled while nothing is ticked.

### Create
Sequential posts, one per ticked row, in this order: kid accounts are already done (they were created on the spot), then chores (per kid, top to bottom), rewards, gigs, then the modules patch when cash is OFF. Progress label "Creating 3 of 11…". A failed row keeps its error under the row and stays ticked; successful rows turn green and untick/lock. The button becomes "Retry failed" when any row failed. (This is E1's `createRows` contract, generalised: `error` lives on the row and the page paints from it.)

### Done
Summary: "Created 8 chores, 4 rewards, 2 gigs." plus two buttons:
- **Refine with Jarvis** (only when the draft response says `ai_available = true`): `/parent/jarvis?q=<prefill>`, prefill ≤ 2000 chars, built client-side (§7).
- **Go to my hub** → `/parent`.

### Entry points
- `SetupCard.astro` (parent hub, while setup is incomplete): the top link changes from "📦 Start in minutes with an age starter pack" → `/parent/starter-packs` to "✨ Set up my family in 2 minutes" → `/parent/setup`. Nothing else on the card changes; the starter-packs page is still linked from the wizard's step 1 and from the Members page as today.
- The More sheet / settings do not change.

## 4. Backend

### 4.1 Starter pack tags
Every chore item in `backend/app/data/starter_packs.py` gains `"tags": [...]` with one or more of the six priorities: `routine`, `school`, `home`, `kitchen`, `pets`, `self_care`. `PRIORITY_TAGS = frozenset({...})` lives next to `AGE_BANDS`. Gigs and rewards carry no tags (rewards filter by `category`, gigs by `wants_gigs`). Invariant test: every chore of every pack has ≥ 1 tag and only known tags.

### 4.2 Shared name matching
`chart_scanner_service.py`'s `Member`, `fold` and `match_members` move to `backend/app/services/name_match.py` (the chart scanner imports them from there; its tests keep passing unchanged). E3 matches each wizard kid name against the family's active + approved members exactly like E1: full name or unique first name, ambiguous first name → unmatched.

### 4.3 Endpoint
`POST /api/families/onboarding/setup-draft` — `require_parent_role`, `@limiter.limit(AI_LIMIT)`. Stores nothing.

Request (`SetupDraftRequest`):
```
kids: list[KidAnswer]            # 1..10; KidAnswer = {name: str (1..60), age_band: str in AGE_BANDS, member_id: UUID | None}
priorities: list[str]            # subset of PRIORITY_TAGS, deduped, ≤ 6
note: str | None                 # ≤ 300, control chars stripped (same normaliser as the teen check-in note)
reward_styles: list[str]         # subset of {screen_time, treats, activities, privileges, toys}, ≤ 5
wants_gigs: bool                 # default True
lang: "es" | "en"                # default "en"
```
`member_id` is client-supplied: the service re-resolves it against the family's members and ignores an id that is not a member of the caller's family (falls back to name matching). A name that matches a member while `member_id` is null also binds — so a parent who typed "Sofía" for a kid who joined meanwhile gets her chores assigned.

Response (`SetupDraftResponse`):
```
source: "ai" | "pack"
ai_available: bool               # family tier allows ai_features AND an LLM is configured
ai_failed: bool                  # ai_available and the AI path raised/parsed nothing → pack used
kids: list[KidDraft]             # KidDraft = {name, age_band, member_id | None, chores: list[ChoreDraft]}
rewards: list[RewardDraft]
gigs: list[GigDraft]             # empty when wants_gigs is False
```
```
ChoreDraft  = {title (1..200), points (0..1000), days: list[int] (0=Mon..6=Sun, sorted unique; [] = every day), is_bonus: bool, description: str | None (≤ 1000), duplicate_of: str | None}
RewardDraft = {title (1..200), points_cost (1..10000), category: RewardCategory minus money, description: str | None, duplicate_of: str | None}
GigDraft    = {title (1..200), points (1..10000, cash MXN), difficulty (1..3), category: GigCategory, duplicate_of: str | None}
```
`duplicate_of` is the existing family title (TaskTemplate `title`/`title_es` for chores, Reward `title`, GigOffering `title`) whose `fold()` equals the draft title's — the review page unticks such rows.

Errors: 422 on bounds (Pydantic); 403 is NOT used for the free plan (the gate is silent, §4.5). The AI path never surfaces a 502: any failure degrades to the pack path with `ai_failed = true`.

### 4.4 Service — `backend/app/services/setup_draft_service.py`
```
PRIORITY_TAGS, REWARD_STYLES, CHORES_PER_KID_MAX = 8, REWARDS_MAX = 6, GIGS_MAX = 4
PACK_CHORES_PER_KID = 6, PACK_REWARDS = 5, PACK_GIGS = 3

band_for_birthdate(birthdate: date, today: date) -> str          # <6 → "3-5", 6-8, 9-12, ≥13 → "13+"
pack_draft(answers, lang) -> (kids, rewards, gigs)               # deterministic, pure
build_prompt(answers, members_summary, lang, examples) -> str    # examples = band pack chores/rewards/gigs for the bands in play
parse_draft(raw_text, answers) -> (kids, rewards, gigs)          # regex JSON, bounded, clamped, validated; raises DraftParseError on no usable JSON
mark_duplicates(kids, rewards, gigs, existing_titles)            # fills duplicate_of using fold()

class SetupDraftService:
    async def draft(db, family_id, answers) -> SetupDraftResponse
```
`draft()`:
1. Load active + approved CHILD/TEEN members; bind `member_id` per kid (explicit id if it belongs to the family, else name match).
2. `ai_available = settings.LITELLM_API_KEY and await family_tier_allows(db, family_id, "ai_features")`.
3. If `ai_available`: call `get_llm_client().chat.completions.create(model=CATEGORIZER_MODEL, max_tokens=3072, temperature=0.4, messages=[system, user])` via `asyncio.to_thread` (same shape as the chart scanner), then `parse_draft`. On any `Exception` (transport, timeout, `DraftParseError`): log at warning, `ai_failed = True`, fall through.
4. Else, or on failure: `pack_draft`.
5. `mark_duplicates` against the family's existing titles; return.

**Pack path** (`pack_draft`):
- Chores per kid: the kid's band pack chores whose `tags ∩ priorities ≠ ∅`; if the family picked no priorities or the intersection is empty, the whole band list. First `PACK_CHORES_PER_KID` in pack order. `days = []`, `is_bonus = False`, `description = None`.
- Rewards: union over the kids' distinct bands, in band order, filtered by `category ∈ reward_styles` (no styles → all), deduped by `fold(title)`, first `PACK_REWARDS`.
- Gigs: when `wants_gigs`, union over bands, deduped, first `PACK_GIGS`; else `[]`.
- Titles in `lang`.

**AI path** (`build_prompt` / `parse_draft`):
- System: you are helping a parent in Mexico (or an English-speaking family when `lang = en`) set up a chore & reward board; reply with ONE JSON object and nothing else. The schema is spelled out in the prompt with the bounds; day names allowed (`normalize_days` from the chart scanner handles numbers, en/es names, `weekdays`/`weekends`).
- User: the kids (name + band + whether they already use the app), priorities, note, reward styles, whether cash gigs are wanted, and the band packs as "examples of the right size and tone — adapt, do not copy blindly". Ask for `CHORES_PER_KID_MAX` chores max per kid with ≤ 2 marked `is_bonus`, `REWARDS_MAX` rewards, `GIGS_MAX` gigs (0 when cash is off), titles in the family language, no kid names inside titles, no money rewards.
- `parse_draft`: first `{…}` block by regex, `json.loads`; kids matched to the answers by `fold(name)` (an unknown kid is dropped; a kid missing from the reply gets `[]`); every string bounded (`[:200]`, descriptions `[:1000]`), `points` clamped with the ranges above (`clamp_points`-style, default 10 for chores, 50 for rewards, 20 for gigs), `category` validated against the enum (unknown → `privileges` / `other`), `difficulty` → 1..3 (default 1), `is_bonus = raw.get("is_bonus") is True`, list caps applied. No usable JSON or zero chores for every kid → `DraftParseError`.

### 4.5 Gating
The draft endpoint is a **silent** gate: `family_tier_allows(ai_features)` decides whether the LLM runs; a free family gets the pack path and HTTP 200. `test_ai_gating.py` gains the pair: free family → `app.core.llm.OpenAI` never constructed, `source = "pack"`, `ai_available = false`; paid family → constructed once. The route still carries `AI_LIMIT` because the paid path spends LLM budget.

### 4.6 Nothing is stored by the draft
The draft response is the only output. Creation goes through the ordinary endpoints from the browser: `POST /api/task-templates/`, `POST /api/rewards/`, `POST /api/gigs/offerings`, `POST /api/auth/register`, `PATCH /api/families/me` (`enabled_modules`). No new tables, no migration, no new onboarding event type (the existing `task_created` / `reward_created` state flips by itself once rows exist).

## 5. Frontend

### 5.1 `frontend/src/lib/setupWizard.ts` — copy + pure logic
- `SETUP_COPY` (ES/EN): step titles, chip labels (`PRIORITY_LABELS`, `BAND_LABELS`, `REWARD_STYLE_LABELS`), buttons, banners, the unjoined-kid sentences, progress label template, done summary template, Jarvis button, errors (`createFailed`, `draftFailed`, `accountFailed`).
- `kidRowsFromMembers(members, today)`: active + approved CHILD/TEEN → `KidRow{name, band, memberId, locked: true, included: true}`; band from `birthdate` when the member payload carries one (it does not today — `UserResponse` hides it — so the fallback by role applies; the function takes the field optionally so a later payload change needs no code here).
- `draftRequest(state)`: wizard state → `SetupDraftRequest` body (included rows only, trimmed names, deduped chips).
- `reviewRows(draft)`: → `{kids: KidReview[], rewards: Row[], gigs: Row[]}` where every row has `{key, included: !duplicate_of, title, points, days?, isBonus?, category?, difficulty?, duplicateOf, status: "idle" | "creating" | "done" | "error", error: string | null}`.
- `choreBody(row, kidMemberId, lang)`: FIXED + `[kidMemberId]` when the kid has an id, else `assignment_type: "auto"`, `assigned_user_ids: null`; `title_es`/`description_es` when `lang = es`; `interval_days: 1`; `days_of_week` null when empty.
- `rewardBody(row)`, `gigBody(row)`, `registerBody(kid, email, password)` (role by band), `modulesBodyWithoutGigs(current: string[] | null)` (null → all togglable minus `gigs`; list → list minus `gigs`).
- `createAll(plan, post, onProgress)`: runs the ordered posts, sets `status`/`error` per row, returns the created counts. `post` is injected (like E1) so the lib is testable without a DOM.
- `jarvisPrefill(state, counts, lang)`: "I just set up my family with the wizard: Sofía (6-8), Diego (13+). Priorities: routine, school. Created 8 chores, 4 rewards, 2 gigs. Help me adjust them — for example…" clamped to 2000 chars.

### 5.2 `frontend/src/pages/parent/setup.astro`
Server side: `require parent`, fetch `/api/families/me` (members) and `/api/families/join-code/current`. Client side: a vanilla `<script>` island importing the lib; steps rendered from one template with `data-step`; all copy from the lib; no native dialogs (`confirmSheet` for "Leave setup? Your answers are not saved" on Back from step 4 — a plain Back on steps 2–3 needs no confirm). Buttons through `buttonClass`. Mobile first (390 px), `pb-safe` above the BottomNav.

### 5.3 Astro proxy routes
- `frontend/src/pages/api/families/onboarding/setup-draft.ts` — POST only, forwards JSON with the bearer cookie (same shape as `starter-packs/apply.ts`).
- Existing and sufficient (verified): `auth/register.ts` (POST), `families/me.ts` (GET/PATCH/DELETE), `families/join-code/current.ts` + `generate.ts`, and the `[...path]` catch-alls for `task-templates`, `rewards` and `gigs`. Guard test lists the new route file.

### 5.4 `SetupCard.astro`
Link swap per §3 "Entry points". Copy inline ES/EN like the rest of the card (the card already carries inline copy).

## 6. Edge cases and errors

1. **No kids at all** (no members, none added): step 1 cannot advance.
2. **Draft request fails (5xx / network):** toast `draftFailed`, stay on step 3 with the answers intact, button re-enabled.
3. **AI timeout / bad JSON:** server falls back (`ai_failed`), review shows the banner, flow continues.
4. **Duplicate titles:** unticked, labelled, can be re-ticked (then the ordinary create runs — it may 409/422 and the error stays on the row).
5. **Account creation 409 (email in use):** error under the mini-form; the kid stays unjoined; the parent can continue.
6. **Kid joined between step 1 and Create:** the draft already bound `member_id` by name; the review card shows "joined" when the draft says so.
7. **Cash OFF but family already had gigs:** the modules patch still removes `gigs` from the enabled list (parent asked for it); existing gig rows are untouched.
8. **Partial Create failure:** failed rows keep errors; "Retry failed" re-posts only `status = error` rows; done rows are never re-posted (no duplicates).
9. **Leaving mid-way:** nothing was stored by the draft; created rows (accounts, chores) exist — the page says so in the Back confirm from step 4 only after at least one row is `done`.
10. **Free plan:** identical UI minus the Jarvis button and the AI banner. No upsell on this page (it works).

## 7. Jarvis hand-off
Only `?q=` prefill (existing deep-link, clamped to 2000). No new Jarvis tool, prompt or endpoint. The parent sends the message themselves; Jarvis uses its ordinary tools (create/update templates, rewards, gigs) under the ordinary HITL gate.

## 8. Testing

Backend (`tests/test_setup_draft.py`, `tests/test_starter_pack_tags.py`, additions to `test_ai_gating.py`, `test_chart_scanner.py` unchanged after the import move):
- pack tags invariant; `band_for_birthdate` boundaries (5/6, 8/9, 12/13);
- `pack_draft`: priority filter, empty-intersection fallback, caps, reward style filter, dedup across bands, gigs off → `[]`, lang;
- `parse_draft`: happy JSON, surrounding prose, unknown kid dropped, missing kid → `[]`, clamps and caps, bad category defaults, `is_bonus` only on literal true, no JSON → `DraftParseError`;
- `SetupDraftService.draft`: member binding by id and by name (foreign id ignored), AI path called with the mocked `OpenAI`, exception → pack + `ai_failed`, free family never constructs the client, duplicates marked against existing TaskTemplate/Reward/GigOffering titles;
- route: 422 on 0 kids / 11 kids / bad band / bad priority / note > 300, kid-role 403, parent 200, nothing persisted (row counts unchanged after the call).

Frontend (vitest): `setupWizard.test.ts` for every pure function (incl. `createAll` with an injected `post` returning a failure for one row; retry re-posts only that row; `jarvisPrefill` clamp; `modulesBodyWithoutGigs` for null and list); `setup-page.test.ts` structure (copy only from the lib, `data-step` for 4 steps, no native dialogs, proxy route file exists and is POST-only); `SetupCard` link assertion updated.

Mutation checks (per the session discipline): flipping the priority filter, the duplicate tick default, the role-by-band rule and the retry filter each fails a named test.

## 9. Docs
- `docs/USER_GUIDE_EN.md` / `_ES.md` §1.3 Family Setup: new sub-section "Guided setup (2 minutes)" before "Invite by email", describing the four steps, the free vs AI difference, the unjoined-kid rule and the Jarvis hand-off.
- `CLAUDE.md`: an "Onboarding — guided setup" paragraph under the onboarding tours section (draft stores nothing; silent AI gate; pack tags; name matching shared with E1).
- `logs/SESSION-WORKLOG.md`, memory `project_ux_program_2026_09.md`.

## 10. Out of scope
- Parent-created kid profiles without email / PIN login (E4 candidate; the kiosk `pin-view` exists but accounts still need an email).
- Persisting wizard answers (no `families.setup_profile`).
- Module suggestions beyond the gigs toggle.
- Re-running the wizard for an existing family with a different pack per kid (works, but no special "re-setup" UX).
- Voice input (E2, next).
