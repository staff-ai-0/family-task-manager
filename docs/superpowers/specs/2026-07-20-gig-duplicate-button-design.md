# Gig Duplicate Button — design

Date: 2026-07-20

## Problem

Parent recreating a similar gig posting (e.g. same chore next week) must retype every field from scratch. No quick "reuse" path on `/parent/gigs`.

## Decision

- **Scope**: active gigs only, on the existing `/parent/gigs` offerings list. No archived-gigs view added (that would be new scope).
- **Behavior**: "Duplicate" opens the existing create/edit modal, prefilled from the source gig, with `gig_id` cleared and the title suffixed `" (copia)"` / `" (copy)"`. Parent reviews/tweaks and hits Save → `POST` creates an independent new offering. Source gig is untouched.

## UI change

`frontend/src/pages/parent/gigs.astro`, active-offerings card block (~line 235-255):

- Add a 3rd button "Duplicar" / "Duplicate" next to Edit/Archive, same `flex-1` row as the current 2-button pattern (confirmed via screenshot) — no layout rework needed, just a third flex child.
- New button carries the same `data-*` fields as `.edit-gig-btn` (title, description, points, difficulty, category, allow_multiple, payout_cadence). No `data-id`.
- New click handler: `fillModalFromDataset(btn)` → clear `editIdInput.value = ""` → append the copy suffix to `#f-title` → `openModal("Duplicar {term}" / "Duplicate {term}")`.
- Existing submit handler already branches on `editIdInput.value` being empty → POST (create path). No submit-handler change needed.

## Out of scope

- No backend/service/model/migration changes — reuses `POST /api/gigs/offerings` as-is.
- No archived-gigs view.
- No new automated test — pure frontend reuse of an already-tested create endpoint. Verify manually in browser per CLAUDE.md's UI-change rule (create a gig, duplicate it, confirm prefilled+suffixed modal, save, confirm two independent cards).
