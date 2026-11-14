# Rules acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Announce the chore rules to every member and record each person's acceptance of the current `rules_version`.

**Architecture:** One new table + `RulesService` + `/api/rules` router; a `RULES_UPDATE` notification; a Layout-mounted `RulesSheet` and a parent-hub status card. Reuses `families.rules_version` (bumped by settings saves) as the version.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, pytest (bare-metal runner), Astro 5 vanilla islands, vitest.

**Spec:** `docs/superpowers/specs/2026-11-13-rules-acceptance-design.md`

## Global Constraints

- Table `rules_acceptances(id uuid pk, family_id fk families ON DELETE CASCADE, user_id fk users ON DELETE CASCADE, rules_version int, snapshot jsonb, accepted_at timestamptz default now)`, `UNIQUE(user_id, rules_version)`, indexed on `family_id`. Alembic: single head, `down_revision` = current head `marked_done_by_parent`; reversible.
- Add the table to `EXPORTED_FAMILY_TABLES` in `backend/app/services/family_export_service.py` (a test in the repo enforces new `family_id` tables are registered).
- Required = Early Bird enabled AND no acceptance row for `(user_id, families.rules_version)`; applies to active, approved members of every role. Each person accepts only for themself.
- `POST /api/rules/accept` body `{version:int}`: 409 `{"code":"stale_version"}` when ≠ current; idempotent when already accepted (returns the existing row, no duplicate); stores a `snapshot` of the values shown.
- `POST /api/rules/announce`: PARENT only, at most once per hour per family (429 otherwise), creates one `RULES_UPDATE` notification per active member (existing `NotificationService.create_localized`), link `/dashboard?rules=1`, returns `{sent:int}`.
- Auto-announce (best-effort, errors logged not raised) when a settings save bumps `rules_version` or turns Early Bird on.
- Never block core flows for non-acceptors; "Más tarde" only hides the sheet for the session.
- Checkbox label (ES): "Entiendo las reglas y las acepto; no haré reclamos futuros sobre resultados calculados con ellas." (EN): "I understand the rules and accept them; I won't make future claims about results calculated under them."
- Frontend: copy only in `frontend/src/lib/rulesNotice.ts`; sheet z-[60] / backdrop z-[55] + safe-area bottom padding; no native dialogs; `hidden` attribute not a class on kit buttons; header tones per CLAUDE.md; proxy file `frontend/src/pages/api/rules/[...path].ts`.
- Family-scoped queries only. Tests: backend via `bash <scratchpad>/pytest.sh <files>` (podman down; Postgres 5435 + redis running), frontend `cd frontend && npx vitest run`, `npm run check`. Agents never run the whole backend suite.

## Review Focus

- A second acceptance of the same version (double-tap) creates one row, not two, and still returns 200.
- A member of family B can never see or accept family A's rules, and a parent of A never sees B's acceptances.
- A family with Early Bird OFF: `required=false`, no sheet, announce still allowed? (announce is refused 409 `early_bird_off` — pin it).
- Version bump while members are mid-session: stale `POST /accept` gets 409 and the UI refetches instead of recording the old version.
- Removed/inactive members are excluded from the counts, announcements and acceptances list.

---

### Task 1: Record, service and read/accept API

**Files:**
- Create: `backend/app/models/rules_acceptance.py`, `backend/app/services/rules_service.py`, `backend/app/schemas/rules.py`, `backend/app/api/routes/rules.py`, `backend/migrations/versions/2026_11_13_rules_acceptances.py`
- Modify: `backend/app/models/__init__.py` (register), `backend/app/main.py` (router), `backend/app/services/family_export_service.py` (`EXPORTED_FAMILY_TABLES`), `backend/app/services/early_bird_rules.py` (expose the ladder/bonus thresholds as named constants and have `week_ladder` use them, if it can be done without changing behavior — existing ladder tests must stay green)
- Test: `backend/tests/test_rules_acceptance.py`

**Interfaces:**
- Produces: `RulesService.snapshot(family) -> dict` (keys: `version, deadline, cutoff, grab_end, alarm_1, alarm_2` as "HH:MM"; `streak_cents:int, chore_bonus_pct:int, floor_pct:int, bonus_tiers:[{early_pct,bonus_pct}]`); `async RulesService.status(db, user) -> dict` (`{required,version,accepted_at,rules}`); `async RulesService.accept(db, user, version:int) -> RulesAcceptance`; `async RulesService.acceptances(db, family_id) -> list[dict]` (`user_id,name,role,accepted_at`; active members only; current version); routes `GET /api/rules/status`, `POST /api/rules/accept`, `GET /api/rules/acceptances` (parent only via `require_parent_role`).

- [ ] **Step 1: Write failing tests** (`test_rules_acceptance.py`): status for teen/child/parent with EB on → `required True`, rules values equal the family's config; EB off → `required False`; accept → row with snapshot, status then `required False` with `accepted_at`; double accept → one row, 200; stale version → 409 `stale_version`; bump `rules_version` → `required True` again and a second row appears after accepting; acceptances list shows accepted/pending per active member, excludes inactive; other family's user never appears; non-parent GET acceptances → 403; unauthenticated → 401; export registry test includes the new table.
- [ ] **Step 2: Run** `pytest tests/test_rules_acceptance.py -v` → FAIL.
- [ ] **Step 3: Implement** model, migration (+ round-trip test following `tests/test_migration_early_bird.py`), service, schemas, routes, export registry, constants. `accept` uses an upsert-safe insert (unique violation → fetch existing).
- [ ] **Step 4: Run** the new tests + the family-export registry test + `tests/test_early_bird_rules.py tests/test_chore_ladder.py` + migration round-trip → PASS; `ruff check app` clean.
- [ ] **Step 5: Commit** `feat(rules): per-member rules acceptance record + API`

### Task 2: Announcement (notification, button, auto on bump)

**Files:**
- Modify: `backend/app/services/notification_service.py` (type `RULES_UPDATE` + ES/EN copy), `backend/app/services/rules_service.py` (`announce`), `backend/app/api/routes/rules.py` (`POST /announce`), `backend/app/services/family_service.py` (auto-announce hook where `rules_version` is bumped / Early Bird turned on)
- Test: `backend/tests/test_rules_announce.py`

**Interfaces:**
- Consumes: `RulesService.status/…` (Task 1), `NotificationService.create_localized(db, family_id, key, user_id=..., params=..., link=..., push_tag=...)`.
- Produces: `async RulesService.announce(db, family_id, *, force: bool=False) -> int` (count sent; raises a 429-mapped error when called again within 1 hour unless `force`; raises 409 `early_bird_off` when EB is off); route `POST /api/rules/announce` → `{sent:int}`.

- [ ] **Step 1: Write failing tests**: parent announce → one `rules_update` notification per active member (all roles, other family untouched), link `/dashboard?rules=1`, ES/EN title by member language; second announce within an hour → 429; EB off → 409 `early_bird_off`; non-parent → 403; settings save that bumps `rules_version` with EB on auto-announces (force, ignoring the hourly cap) and a failure inside the announce never fails the save; enabling EB announces; a save that changes nothing sends nothing.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (`NotificationType`/type string constant, localized copy singular only: "Nuevas reglas de tareas — léelas y acepta" / EN equivalent; hourly cap via an existing notification row since the last `rules_update` for the family, no new column). **Step 4: Run** `test_rules_announce.py test_rules_acceptance.py test_chore_rules_config.py test_early_bird_api.py` → PASS; ruff clean.
- [ ] **Step 5: Commit** `feat(rules): announce rules to every member (+ auto on version bump)`

### Task 3: Frontend sheet, parent status card, proxy, copy

**Files:**
- Create: `frontend/src/pages/api/rules/[...path].ts`, `frontend/src/lib/rulesNotice.ts`, `frontend/src/components/RulesSheet.astro`, `frontend/src/components/parent/RulesStatusCard.astro`
- Modify: `frontend/src/layouts/Layout.astro` (mount the sheet once), `frontend/src/pages/parent/index.astro` (mount the card)
- Test: `frontend/test/rulesNotice.test.ts`

**Interfaces:**
- Consumes: `GET /api/rules/status` → `{required:boolean, version:number, accepted_at:string|null, rules:{version,deadline,cutoff,grab_end,alarm_1,alarm_2,streak_cents,chore_bonus_pct,floor_pct,bonus_tiers:[{early_pct,bonus_pct}]}}`; `POST /api/rules/accept {version}`; `GET /api/rules/acceptances` → `[{user_id,name,role,accepted_at|null}]`; `POST /api/rules/announce` → `{sent}`.
- Produces: `rulesNotice.ts`: `rulesLines(rules, lang): string[]` (one plain line per rule rendered from the family's values), `acceptLabel(lang)`, `statusSummary(rows, lang)` ("3 de 5 aceptaron"), `pendingNames(rows)`, `announceResultMessage(sent, lang)`, `acceptErrorMessage(code, lang)` (stale_version → "Las reglas cambiaron, mira la versión nueva").

- [ ] **Step 1: Write failing vitest tests**: `rulesLines` renders the cutoff/grab/deadline/alarms/streak pesos/ladder lines from a values fixture in ES and EN (non-default values prove nothing is hardcoded); `acceptLabel` equals the exact checkbox strings in Global Constraints; `statusSummary`/`pendingNames` for mixed rows and for an empty list; error message mapping incl. `stale_version`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run test/rulesNotice.test.ts` → FAIL. **Step 3: Implement** the lib, proxy file (`createApiProxy({ name: "rules" })`, same shape as `early-bird/[...path].ts`), `RulesSheet` (fetch `/api/rules/status` after `astro:page-load` per the repo's dispatch convention; show only when `required`, user is logged in, not on kiosk pages, not while the welcome tour runs — reuse ModuleTour's suppression check; checkbox enables Accept; Accept POSTs and on `stale_version` refetches; "Más tarde" sets `sessionStorage` (try/catch) to hide for the session; text from `rulesLines`; `role="dialog"`, focus the checkbox, safe-area padding), `RulesStatusCard` on the parent hub (summary + pending names + Announce button that POSTs and toasts the result with `showToast`; `hidden` when Early Bird is off / `acceptances` empty). **Step 4: Run** `npx vitest run` (all, incl. visual-consistency/contrast/no-native-dialogs), `npm run check` (0 errors), `npm run build` → PASS.
- [ ] **Step 5: Commit** `feat(rules): rules sheet with acceptance checkbox + parent status card`

### Task 4: Docs and verification

**Files:** Modify `CLAUDE.md` (add a short "Rules acceptance" line to the Early bird row or a new row: table, endpoints, auto-announce, no hard lock), `docs/USER_GUIDE_EN.md` + `docs/USER_GUIDE_ES.md` (one short paragraph: the rules sheet and who has accepted), spec status → IMPLEMENTED.

- [ ] **Step 1:** Update docs as above. **Step 2:** Run `ruff check app`, the touched backend test files, the migration round-trip, family-export registry test, vitest + astro check + build. **Step 3:** Commit `docs: rules acceptance`.
