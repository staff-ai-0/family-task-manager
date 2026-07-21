# Gig Duplicate v2 — Repost from History + Action-Row Redesign

Date: 2026-07-20

Follow-up to `2026-07-20-gig-duplicate-button-design.md` (shipped as PR #144). User feedback after using the shipped feature:

1. The intended use case was reposting a gig that had **already closed and dropped off the active list** (e.g. "Bañar a molly" — a single-claim gig that auto-deactivates once its one claim is approved, and is now only visible in the History section). The shipped Duplicate button only works on still-active cards, so it couldn't address this at all.
2. The 3-button flat `flex-1` row (Edit/Duplicate/Archive) looks crowded/undifferentiated on the active card.

## Root cause (why "duplicate from history" wasn't possible)

`GET /api/gigs/offerings` (`backend/app/api/routes/gigs.py:137-152`) never wires an `include_inactive` query param through to `GigOfferingService.list_for_family` — the frontend's `?include_inactive=false` query string is silently ignored server-side, and the route always returns active-only. There was no code path back to a closed offering's fields at all, so History rows (which only carry `gig_title`/`gig_points` via `GigClaimResponse`) had no way to source the difficulty/description/category/allow_multiple/payout_cadence needed to prefill a duplicate.

Deactivation is always soft (`GigOfferingService.deactivate` sets `is_active = False`; there is no hard-delete path), so every historical claim's `gig_id` reliably resolves to a real, if inactive, offering row.

## Research basis

Repost-from-history is a converged pattern across unrelated products — Uber Eats "Order it again", Amazon "Buy it again", Todoist/Trello "Duplicate"/"Copy" — all: the action lives on the historical record, and it always creates an independent new record without touching the original. No family chore app (Greenlight, RoosterMoney, GoHenry, BusyKid, etc.) has documented UX for this specific case; their "repeat" features are a recurrence flag set at creation time, not a repost-from-history action, so they aren't precedent here.

For the 3+-action card layout problem, evaluated kebab menu (Material Design's own recommended threshold for 3+ card actions) against a plain icon-reweight (no new interaction model, pure markup/CSS). User picked icon-reweight for lower build cost.

## Decision

### 1. Backend: wire `include_inactive`

`backend/app/api/routes/gigs.py`, `list_offerings` (~line 137): add `include_inactive: bool = Query(False)` and pass it through to `GigOfferingService.list_for_family(db, family_id, user_id, include_inactive=include_inactive)`. Default stays `False`, so every existing caller (kid board `/gigs`, proposals) is unaffected. This was dead/untested code before — add a regression test in `backend/tests/test_gig_board.py` extending `test_edit_and_deactivate_offering`: after deactivating, assert the offering is absent from the default list (already asserted) AND present when `?include_inactive=true` is passed.

### 2. Frontend data: one fetch, two views

`frontend/src/pages/parent/gigs.astro`: change the offerings fetch to `/api/gigs/offerings?include_inactive=true`. In the frontmatter, derive:
- `activeOfferings` — `is_active` true, feeds the existing "Gig offerings" card section unchanged.
- `offeringById` — a `Map` over ALL returned offerings (active + inactive), keyed by offering id. Used only to enrich History rows.

### 3. History rows get a conditional "Repost" button

For each history row `c`, look up `offeringById.get(c.gig_id)`. If found and `offering.is_active === false`, render a button with the same `.duplicate-gig-btn` class and the same `data-*` attributes (title/description/points/difficulty/category/allow_multiple/payout_cadence) already used by the active-card Duplicate button, sourced from `offering` instead of the claim. No new JS: the existing `document.querySelectorAll(".duplicate-gig-btn")` click-wiring (from PR #144) already covers any element with that class present at page load, including these.

If the offering is still active, render nothing extra — the active-card Duplicate button already covers that case, per the "keep both" decision.

Label (distinct from the active-card button, matching the reorder-precedent's explicit verb): `"↻ Repostar {gt.one}"` / `"↻ Repost this {gt.one}"`.

### 4. Active-card layout: icon-reweight

Active-card button row becomes: Edit (unchanged, full label, primary weight) + two small icon-only buttons — Duplicate (📋) and Archive (🗄️) — each with an `aria-label` (`"Duplicar"/"Duplicate"`, `"Archivar"/"Archive"`) since the visible text label is removed. Pure markup/CSS change; the existing `.edit-gig-btn`/`.duplicate-gig-btn`/`.archive-gig-btn` classes and click handlers are untouched.

## Out of scope

- No kebab/overflow menu (declined in favor of icon-reweight).
- No change to the kid-facing `/gigs` board or proposal review flow.
- No swipe gestures, bottom sheets, or other new interaction models.
- History rows for still-active gigs get no new button.

## Testing

- Backend: new pytest case (see above) — this is a real route change, unlike the v1 button-only change, so it gets a real test.
- Frontend: no new automated test (same judgment as v1 — pure prefill/markup reuse of an already-tested path); manual browser verification: deactivate a gig, confirm it appears in History with a Repost button, confirm the button prefills the modal correctly, confirm Save creates a new active offering. Also verify the icon-reweight buttons work identically to before (functionality unchanged, only markup/labels changed) and have working `aria-label`s.
