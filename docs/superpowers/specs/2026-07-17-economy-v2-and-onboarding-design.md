# Economy v2 + Action-Driven Onboarding — Design

**Date:** 2026-07-17
**Branch:** `qa/wk29-jesus-feedback`
**Origin:** WK29 QA notes from Jesús (obsidian-qa-notes-family-app) + economy-model
decision from Juan (2026-07-17).

---

## 1. Problem

Two intertwined problems surfaced in WK29 QA:

1. **Stale economy copy.** The onboarding intro banner tells families "los puntos
   nunca se vuelven dinero" and frames points and cash as strictly separate. That
   contradicts the shipped Family Bank `chore_proportional` allowance (points-driven
   weekly cash) and no longer matches how Juan wants the economy to read.

2. **Text-heavy, passive onboarding.** The current welcome tour is 6–8 driver.js
   tooltips that *describe* tabs. Testers (Manuel, via Jesús) found it "entendible"
   but wordy, with no path to actually do anything — "crea tareas" with no way to
   create a task. Fonts on info banners read as hard to scan.

This design reconciles the economy model into a single canonical story ("v2") and
rebuilds onboarding around *doing* the first task and first gig, on the real UI.

## 2. Canonical economy model (v2)

Two currencies with clearer boundaries. **Additive** — nothing existing is removed.

### Puntos (points) — weekly behavior currency
- Obligatory (required, non-bonus) weekly chores each carry points. The sum of a
  kid's assigned obligatory points for the week is their weekly total (Jesús's
  "250" — **derived per family, not a new config value**; it is whatever the
  assigned obligatory templates sum to).
- Points keep their current use: spend on **premios/privilegios**
  (`Reward.points_cost`) — unchanged.
- Points gain a second, layered meaning: completing (and getting approved for)
  obligatory chores **unlocks the weekly *domingo* payout** (allowance).

### Domingo (allowance) — weekly cash from chores
- Parent sets a weekly cash **cap** (`KidBankAccount.allowance_cents`, already
  exists).
- Two release modes (`allowance_mode`):
  - `chore_proportional` (**exists**): pay `cap × done/assigned`, floored, ≤ cap.
  - `chore_gated` (**NEW**): pay the **full cap iff 100%** of assigned obligatory
    points are completed-and-approved that week; otherwise pay 0. This is Juan's
    "si se cumplen con **todas** las tareas obligatorias."
- Parent picks the mode. Onboarding sets `chore_gated` as the default it teaches,
  because it matches the "finish everything → get your domingo" mental model.

### Dinero (cash) — gig currency, extra
- Gigs pay cash. Cash **already** accrues to `users.cash_cents` on gig approval
  (`CashService.award_gig_cash`) and is physically paid out later by a parent
  (`record_payout`, the "Pagar dinero ganado" button). This two-phase model stays.
- **NEW:** each gig carries a **payout cadence**
  (`GigOffering.payout_cadence`): `immediate` (default = today's behavior),
  `weekly`, `biweekly` (quincena), `monthly`. Cadence does **not** change accrual;
  it drives *when the parent is reminded to pay out* the accrued cash and how the
  payout screen groups earnings. `immediate` gigs are reminded/surfaced as soon as
  approved (unchanged UX).

### Naming
- Keep **"Gig"** as the product term (Juan's call — it is in the DB, URLs, and
  brand). Copy must clarify a gig is **extra dinero**, distinct from a **premio**
  (points reward). Fix the tour line that conflates the two.

## 3. Scope — five work items

| # | Item | Layer | Size | Risk |
|---|------|-------|------|------|
| 1 | `chore_gated` allowance mode | backend | S | low |
| 2 | Gig `payout_cadence` | backend + migration | M | low |
| 3 | Economy copy rewrite (v2) | frontend i18n | S | low |
| 4 | Action-driven onboarding missions | frontend | L | med |
| 5 | Readability polish (fonts, shorter (i) boxes, GIF slots) | frontend | S–M | low |

### 3.1 Backend — `chore_gated` allowance mode
- Add `"chore_gated"` to `ALLOWANCE_MODES` (`bank_service.py`) and the
  `allowance_mode` check-constraint / validation.
- New pure helper `_chore_paycheck_gated(cap, done, assigned) -> int`: returns
  `cap` iff `assigned > 0 and done == assigned`, else `0`. (Keep
  `_chore_paycheck_cents` for proportional untouched.)
- `chore_paycheck_preview` + `release_chore_paycheck` branch on mode to pick the
  helper. `release_chore_paycheck`'s `!= "chore_proportional"` guard becomes
  "is a chore-* mode" (accept both `chore_proportional` and `chore_gated`).
- `_chore_points` (done/assigned over non-bonus assignments) is reused as-is; it
  already counts only completed-&-approved.
- **Tests (TDD):** gated pays full cap at 100%; pays 0 at 99%; pays 0 when nothing
  assigned; proportional mode unaffected; preview reports the right `projected_cents`
  and `mode`.

### 3.2 Backend — gig `payout_cadence`
- New column `GigOffering.payout_cadence String(10) NOT NULL default 'immediate'`
  with a check-constraint over the four values. Alembic migration (single head;
  CI exercises upgrade → downgrade -1 → upgrade).
- Schema: add `payout_cadence` to gig create/update/read Pydantic models
  (default `immediate` so existing clients and older mobile builds are unaffected).
- Cash payout **reminder** grouping: where the payday reminder / cash summary is
  produced, group unpaid gig cash by the originating gig's cadence so the parent
  sees "listo para pagar (semanal)" vs "(quincenal)". Accrual code path unchanged.
- **Decision (kept simple to bound scope):** cadence is **advisory** — it never
  blocks a parent from paying out early, and no scheduler auto-pays. It changes
  reminders + grouping only. Auto-release on a schedule is explicitly out of scope
  (future spec if wanted).
- **Tests:** column defaults `immediate`; create/read round-trips a cadence;
  migration up/down clean; existing gig tests still green.

### 3.3 Economy copy rewrite (v2)
- Rewrite `intro_banner_title` / `intro_banner_body` (EN + ES, `i18n.ts`) to the
  v2 story, **≤ 2 short sentences**, ending with a "ver más / learn more" link to
  `/ayuda` (`/help`). Remove "los puntos nunca se vuelven dinero".
  - ES direction: "Dos monedas. Termina tus tareas obligatorias para ganar puntos
    (cámbialos por premios) y desbloquear tu domingo semanal. Las gigs son dinero
    extra que un padre te paga. [Ver cómo funciona]"
- Fix `tour_p_manage_body` ("Gestión es tu base…") — clarify how to *create* a
  task, drop the awkward phrasing.
- Audit tour steps for gig-vs-premio confusion; correct any step that implies a
  gig is a reward.
- Update `docs/USER_GUIDE_{EN,ES}.md` economy section to match v2 (the `/ayuda`
  target).

### 3.4 Action-driven onboarding missions
The heart of the rebuild. Replaces passive tooltips with *do-it* missions.

**Structure**
- The dashboard **getting-started checklist** (`#onboarding-widget`, "¡Empecemos!")
  is the hub. Each checklist item becomes a **mission** launchable in place.
- **Mission 1 — Crea tu primera tarea** (replicates Jesús's mockups):
  coach-marks walk the real Task flow, advancing on **real user action**, not a
  "Siguiente" button:
  1. highlight the `+` FAB on `/parent/tasks` → advance when the create modal opens
  2. highlight the template picker → advance when a template is chosen
  3. highlight Asignar → advance when a member is selected
  4. highlight Puntos (with the "1 pto ≈ tu semana de 250 / domingo" hint) →
  5. highlight "Crear tarea" → advance when the task is created → mission complete,
     check the checklist item, return to hub with a "ahora crea una gig" nudge.
- **Mission 2 — Publica tu primera gig**: same pattern on `/gigs` (Nueva Gig →
  título → recompensa → cadencia → publicar). Teaches gig = extra dinero + the new
  cadence field.
- Remaining checklist items (invitar hijo/a, aprobar primera tarea) keep their
  existing deep-link behavior for now; only tasks + gigs get full instrumentation
  this pass.

**Mechanism**
- Extend `tourSteps.ts` with a `mission` shape: each step gains an optional
  `advanceOn` = `{ event: string, match?: selector }` describing the real DOM
  signal that completes it (e.g. `modal-open`, `template-selected`,
  `task-created`). Emit these as `CustomEvent`s from the existing task/gig modal
  scripts (small, additive dispatches — no logic change).
- New `missionRunner` (client, alongside `tour.ts`) drives driver.js highlights
  and listens for the `advanceOn` events instead of wiring Next buttons. Falls
  back to a Next button if the expected event does not fire within a timeout, so a
  moved target degrades to today's tooltip rather than a dead end.
- Cross-page continuity: mission state persists in `sessionStorage`
  (`ftm_mission_<id>_step`) so navigating tasks→dashboard→gigs resumes correctly.
  Per-user keyed like the existing tour guard.
- Persistence + acking reuse the existing tour ack (`completed_welcome_tour`
  flag + localStorage guard). Replaying is available from the existing
  `TourReplayButton`.

**Degradation / safety**
- Missions are **skippable** at every step (driver.js close acks, same as today).
- If a mission target element is absent (feature flag, role, empty state), the
  mission is skipped and the checklist item stays actionable via deep-link.
- Build behind the current tour: the classic tooltip tour remains the fallback
  path; missions are the enhanced path when targets are present.

### 3.5 Readability polish
- Bump info-banner body font size + contrast (the yellow "Cómo funcionan…" card and
  the (i) boxes): raise from the current small/soft treatment to the body scale used
  elsewhere; verify against both themes.
- Shorten every (i) info box to 1–2 lines + "ver más" → `/ayuda`.
- **GIF slots:** scaffold `<img>` slots + captions in the (i) boxes / help pages now
  (with `loading="lazy"` and `alt`), referencing asset paths under
  `frontend/public/onboarding/`. Asset production (screen recordings) is a
  **follow-up** — the branch is not blocked on it; slots render a static
  placeholder/first-frame until files land.

## 4. Data / API changes

- **DB:** `kid_bank_accounts.allowance_mode` gains a legal value `chore_gated`
  (constraint update, no column add). `gig_offerings` gains `payout_cadence`
  (new column, default `immediate`). One Alembic revision, single head.
- **API:** gig create/update/read gain optional `payout_cadence`
  (default `immediate`). Bank config accepts `chore_gated`. Both backward
  compatible; older mobile builds omitting the fields keep working.
- **No breaking change** to points, rewards, or cash accrual.

## 5. Testing

- Backend: pytest for gated allowance math + gig cadence round-trip + migration
  up/down (CI already gates on the alembic round-trip and ≥70% coverage). All new
  behavior TDD (red → green).
- Frontend: `astro check` + build. e2e (Playwright) — extend `welcome-tour.spec.js`
  (or new `onboarding-missions.spec.js`) to cover: mission 1 advances on real task
  creation; skip/close acks; degraded fallback when a target is absent. Reuse the
  demo Plus family (`mom@demo.com`) for gated paths.
- Verify economy copy renders v2 (no "nunca se vuelven dinero") in EN + ES.

## 6. Out of scope (explicit)

- Scheduler-driven **auto-payout** of gig cash on cadence (cadence is advisory
  only this pass).
- Deprecating / re-pricing the points→rewards store (kept additive per decision).
- A configurable numeric weekly points target ("250" is derived, not stored).
- Full GIF asset production (slots scaffolded; recordings follow-up).
- Instrumented missions for invite / approve steps (deep-link only this pass).

## 7. Rollout

- All work on `qa/wk29-jesus-feedback` (already carries the Jarvis + More-sheet
  fixes from this QA pass). One PR to `main`.
- Migration ships with the deploy; `deploy-onprem.sh` runs alembic against the new
  image before bringing the stack up.
- No env-var or infra changes.
