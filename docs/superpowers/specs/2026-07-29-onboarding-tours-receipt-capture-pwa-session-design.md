# Design — Module tours, one-tap receipt capture, PWA session resume

**Date:** 2026-07-29
**Status:** Approved (design), pending implementation plan
**Scope:** Three independent UX changes, shipped as three PRs in the order below.

---

## Why these three

All three are friction the user hits daily:

1. **Session dies on every PWA launch.** The installed (Add-to-Home-Screen) app forces a
   Google sign-in on nearly every cold start, even though a 30-day refresh token is sitting
   valid in the cookie jar.
2. **Receipt capture takes three taps and a page load** before the camera opens, across a
   screen with three near-redundant buttons.
3. **Onboarding is one flat six-step tour.** Nothing teaches the budget, the gig board, or
   the chore/reward loop — the three surfaces with the most concepts.

They share no code. PR order is by user impact: A (bug) → B (flow) → C (feature).

---

## A · PWA session resume

### Root cause (confirmed by code inspection, 2026-07-29)

| Fact | Location |
|---|---|
| PWA cold-launch always lands on `/` | `frontend/public/manifest.webmanifest` → `"start_url": "/"` |
| `/` is a public route | `frontend/src/lib/security/request-guards.ts:19` (`PUBLIC_ROUTES`) |
| Public routes return from middleware **before** the transparent-refresh block | `frontend/src/middleware.ts:168` (early return) vs `:214` (refresh) |
| The landing page only checks the access token | `frontend/src/pages/index.astro:12` — `if (Astro.cookies.has("access_token"))` |
| The access-token cookie lives 1 hour | `frontend/src/lib/auth-cookies.ts:1` — `ACCESS_MAX_AGE = 60 * 60` |

Chain: more than an hour after last use, the browser has already discarded `access_token`.
The PWA opens `/`; the middleware short-circuits on the public-route check and never looks
at `refresh_token`; `index.astro` sees no access token and renders the **marketing landing
page**. The user taps "Log in" and re-authenticates with Google. The 30-day refresh token
was valid the whole time and was simply never consulted.

Not iOS-specific in cause. The PWA hits it every launch because it always starts at `/`;
browser users usually re-enter through `/dashboard` (history, bookmark), which is a
protected route and therefore does refresh correctly.

Ruled out during diagnosis, so nobody re-opens them:

- **Refresh-token rotation race** — `backend/app/api/routes/auth.py:110-157` validates
  `token_version`, it does not consume a one-time token. Concurrent cold-start refreshes
  all succeed.
- **`token_version` churn** — bumped only by logout-everywhere, password reset, family
  deletion, and admin actions. A normal login on a second device does not invalidate the
  first.
- **Service worker** — `frontend/public/sw.js` is network-first for navigations and never
  caches `/api/*`.
- **Cookie attributes** — `HttpOnly; Secure; SameSite=Lax; Max-Age=2592000` on the refresh
  cookie, set server-side. Not subject to the ITP 7-day script-cookie cap.

### Change

1. `frontend/src/middleware.ts` — move the transparent-refresh block so it runs **before**
   the `isPublicRoute` early return.
   - Guard unchanged: fires only when `isJwtExpired(accessToken) && refreshToken`. An
     anonymous visitor (no refresh cookie) triggers zero extra backend calls, so marketing
     traffic and crawlers are unaffected.
   - Skip when `path === "/api/auth/refresh"` — that route *is* the refresh, and calling it
     from its own middleware pass would recurse.
2. The public-route response path must append `refreshedSetCookies` before returning.
   Without this the rotated pair is minted and thrown away, and the next request repeats
   the refresh.
3. `frontend/src/pages/index.astro` — unchanged logic, but now sees a live `access_token`
   and 302s to `/dashboard`. Keep the existing behaviour when refresh fails (render the
   landing page).
4. `frontend/src/pages/login.astro` — same treatment: if a valid session survives the
   middleware pass, redirect to the validated `?next=` path, else the role home, instead of
   showing the form.

No cookie-TTL change. No backend change. No migration.

### Tests

- `frontend/test/middleware.test.ts`
  - public route + expired access + valid refresh → backend refresh called, `Set-Cookie`
    present on the response;
  - public route + **no** refresh cookie → zero backend calls (guards the crawler cost);
  - `/api/auth/refresh` itself → no refresh attempt (no recursion);
  - protected-route behaviour unchanged (regression).
- E2E (`e2e-tests/`): delete `access_token`, keep `refresh_token`, `GET /` → 302
  `/dashboard`; same for `/login`.

### Risks

- Public pages now perform one backend round-trip for visitors carrying a refresh cookie.
  Bounded: one call, only when the access token is dead, and it replaces a full re-login.
- `/help`, `/ayuda`, `/privacidad`, `/terminos` will start redirecting nothing — they render
  normally either way; only `/` and `/login` branch on session state.

---

## B · One-tap receipt capture

### Current flow

Budget page → FAB → tap "📸 Escanear" → **full page navigation** to
`/budget/scan-receipt` → tap one of three buttons → camera. Three taps and a page load
before the shutter.

The three buttons are near-redundant on mobile:

| Button | Input | Overlap |
|---|---|---|
| 📷 Tomar foto | `accept="image/*,application/pdf" capture="environment"` | `capture` forces camera-only |
| ⬆ Subir imagen | `accept="image/jpeg,…,application/pdf"` | iOS shows this same sheet |
| 📦 Subir varios | same + `multiple` | differs only by `multiple` |

Dropping `capture` makes iOS present Take Photo / Photo Library / Choose File in one native
sheet, and `multiple` on that same input covers the bulk path. All three collapse into one
hidden input.

### Change

1. New `frontend/src/components/budget/ReceiptScanSheet.astro` — the scan overlay, confirm
   card, duplicate modal, bulk progress panel, and the whole scan script, moved verbatim out
   of `frontend/src/pages/budget/scan-receipt.astro`. Behaviour preserved, including the
   `<template>` + `textContent` XSS-safe rendering, the 403 upsell branch, the 409
   `dup_warning` modal, and the `draft_id` → `/budget/receipt-drafts` redirect.
2. One hidden `<input type="file" accept="image/*,application/pdf" multiple>`. No `capture`.
   One file → confirm card. Several → bulk panel. The visible three-button block is deleted.
3. Mount the sheet in `frontend/src/components/ui/BudgetShell.astro` (`overlays` slot).
   `FABModal` is only rendered by budget pages (`budget/index`, `budget/transactions`,
   `budget/reports`), all of which use `BudgetShell`, so one mount point covers every entry.
   Guard by element id so a page that also renders `scan-receipt` cannot double-mount.
4. Entry points fire an event instead of navigating:
   - `FABModal.astro` "📸 Escanear" and the `budget/transactions.astro` header camera icon
     become buttons dispatching `ftm:scan-receipt` on `window`; the sheet listens and opens
     the picker directly.
   - Both keep an `href="/budget/scan-receipt"` fallback rendered when the sheet is absent,
     so the flow degrades rather than dead-ends.
5. `frontend/src/pages/budget/scan-receipt.astro` becomes a thin wrapper: same auth/role/
   premium frontmatter, renders `BudgetShell` + the sheet, and auto-opens the picker on
   load. Kept because email links, the drafts flow, and `DrawerMenu` point at it.

Result: one tap from any budget page to the native camera sheet; confirm and save without
leaving the page. No backend change — same `POST /api/budget/transactions/scan-receipt`,
same premium metering (one scan per file, unchanged).

### Tests

- E2E: existing budget receipt specs updated for the new entry point; a bulk multi-file
  case; the 409-duplicate modal path.
- No new backend tests — the API surface is untouched.

### Risks

- The FAB now opens an OS sheet with no intermediate page. If the user cancels the picker,
  nothing happens (no state change) — that is the intended no-op.
- Removing `capture` means Android/iOS show a chooser rather than jumping straight to the
  lens. This is the trade for killing the second tap and the two extra buttons, and it is
  what makes bulk work from the same control.

---

## C · Module tours + replay hub

### Today

- `frontend/src/lib/tourSteps.ts` — one driver.js welcome tour: 8 parent steps, 7 kid steps.
- `frontend/src/lib/missionRunner.ts` + `buildMission` — action-driven missions
  (`first-task`, `first-gig`) that advance on real DOM signals.
- `users.completed_welcome_tour` (bool) + a per-user localStorage guard.
- The onboarding checklist widget on `/parent`.

One boolean means one tour. Per-module tours need per-tour state.

### Data model

- Migration (alembic, keep the single-head chain): `users.completed_tours` — JSONB, not
  null, server default `'[]'`, holding tour ids.
- `POST /api/families/onboarding/tours/{tour_id}/complete` in
  `backend/app/api/routes/onboarding.py` — appends the id, idempotent, 204. Unknown id →
  422 against a server-side allowlist. Depends on `get_current_user`, **not**
  `require_parent_role`: kid tours ack through the same route.
- `UserResponse.completed_tours: list[str]` so `/auth/me` carries it; the frontend gates
  auto-start on it.
- Frontend proxy `frontend/src/pages/api/onboarding/tours/[id]/complete.ts`, mirroring
  `api/auth/ack-tour.ts`, callable via `navigator.sendBeacon`.
- `completed_welcome_tour` is left exactly as is. The welcome tour keeps its own flag and
  its own endpoint.

### The five tours

`buildModuleTour(id, role, lang)` in `tourSteps.ts`, reusing the existing `TourStep` shape:

| id | role | Covers |
|---|---|---|
| `budget-parent` | parent | Cuentas → categorías/sobres → asignar dinero → escanear ticket → reportes |
| `gigs-parent` | parent | Publicar un gig → claim del kid → aprobar y pagar → Family Bank |
| `gigs-kid` | kid | Tablero de gigs → tomar uno → enviar prueba → cobrar |
| `chores-parent` | parent | Plantillas → asignación → revisión graduada (full/partial/missed) → premios |
| `rewards-kid` | kid | Puntos → catálogo de premios → canjear |

Constraints:

- 5–6 steps per tour, one idea per step. Title ≤ 40 characters, body ≤ 140.
- ES + EN keys in `frontend/src/lib/i18n.ts`, same `tour_*` naming convention.
- Wording rule from `CLAUDE.md`: "gig" only for the cash board; chores and bonus tasks are
  "tarea"/"task" everywhere else.
- Budget is parent-only (the pages already are) — no `budget-kid`.

### Trigger

- New `frontend/src/components/ModuleTour.astro` — props `tourId`, `role`, `lang`,
  `userKey`, `completed`. Mount points, one per tour:

  | Tour | Mounted in |
  |---|---|
  | `budget-parent` | `frontend/src/components/ui/BudgetShell.astro` (covers `/budget/*`; only fires on `/budget`) |
  | `gigs-parent` | `frontend/src/pages/parent/gigs.astro` |
  | `gigs-kid` | `frontend/src/pages/gigs/index.astro` |
  | `chores-parent` | `frontend/src/pages/parent/tasks.astro` |
  | `rewards-kid` | `frontend/src/pages/rewards.astro` |
- Auto-starts when the id is absent from `completed_tours` **and** no localStorage guard is
  set, following `WelcomeTour.astro`: `astro:page-load` + a self-trigger for the
  already-ready case, 450 ms delay so the nav and header finish painting.
- Suppressed while the welcome tour is running (`window.__ftmTourStarted`) so a brand-new
  parent never gets two overlays stacked.
- `runTour` in `tour.ts` gains an `ackUrl` parameter (default: the existing
  `/api/auth/ack-tour`) so module tours ack to the per-tour endpoint. Both guards are
  written on every exit path, as today.

### Replay hub

- `GuideShell.astro` gains a named `before-content` slot so the hub renders above the
  markdown without polluting the auto-generated TOC.
- `/help` and `/ayuda` render a "Guías interactivas" / "Interactive guides" card grid in
  that slot: one card per tour, filtered by the viewer's role and the family's
  `enabled_modules`.
- Both pages are public. The hub reads the access token in frontmatter and renders nothing
  for anonymous visitors. (After change A, a visitor arriving with only a refresh cookie
  will have a live token by the time the page runs.)
- A card links to `<module-page>?tour=<id>`. The module page force-runs that tour, ignoring
  both the localStorage guard and the DB flag — an explicit replay is not a first visit.
  The DB flag is not cleared.

### Tests

- Backend `backend/tests/test_onboarding_tours.py`: ack is idempotent; unknown id → 422;
  a kid can ack a kid tour; one user's acks never appear on another user's `/auth/me`;
  `completed_tours` survives the migration round-trip (CI already exercises
  upgrade → downgrade → upgrade).
- Frontend unit on `buildModuleTour`: expected step count per id, every i18n key resolves
  in both `es` and `en` (no raw key leaking into copy).
- E2E: a fresh parent gets the budget tour on first `/budget` visit and not on the second;
  a hub card replays it after completion.

### Risks

- Five tours is real copy to maintain. Bounded by the ≤140-character rule and by keeping
  the side modules (meals, shopping, calendar, pet, chat) out of this pass.
- Auto-run tours can annoy. Mitigated by the single-fire DB flag, the welcome-tour
  suppression, and driver.js's always-present close button.

---

## Out of scope

- Tours for meals, shopping, calendar, pet, chat.
- Any change to the existing welcome tour's steps or copy.
- Changing `start_url`, cookie TTLs, or the token model.
- Native iOS/Android app packaging.
