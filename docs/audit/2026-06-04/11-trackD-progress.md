# Track D — UX simplification: progress

Branch `feat/ux-simplify` (stacked on `chore/cleanup`).

## DONE ✓ — budget quick-wins (commit 7e31999)
- **Dead budget nav deep-links repaired.** `SettingsAccordion` rendered its anchor id on the
  inner content div (`accordion-content-<id>`), so every DrawerMenu deep-link
  (`/budget/settings#accounts`, `#payees`, `#rules`, `#recurring`, `#backups`) hit nothing.
  Added `id={id}` + `scroll-mt-20` to the accordion wrapper.
- **"Categories" link** pointed at `#categories`, which has no settings accordion (categories
  live on the main budget view) → repointed to `/budget/`.
- **FAB mislabels fixed.** Camera/receipt button (`/budget/scan-receipt`) read "Photo"; file
  import button (`/budget/import`) read "Scan". Now camera = "Scan", import = "Import"
  (new `fab_import` key; es "Escanear"/"Importar").

Frontend-only, not browser-verified here (no local node_modules) — visual/e2e check recommended.

## NEEDS A PRODUCT DECISION — task ↔ gig unification (the big lever)
Audit finding: TASK and GIG are two parallel "extra-work" systems whose UIs collide —
- The new gig board (`gig_offerings`/`gig_claims`) was deliberately split from mandatory tasks
  (commit d42c479), but kids now see **two** unrelated "gigs" UIs with the same vocabulary.
- Parents have **two** approval screens for what they both call "gigs"; the dashboard badge
  only counts one.
- Gig-mode jargon (Competition / Rotation / Collaboration) leaks into **mandatory-task**
  create/edit; the task create modal silently zeroes non-bonus points.
- "1 pt = $1 MXN" cash framing shown but no cash payout exists.

This is the highest-UX-leverage change but it is opinionated and a substantial frontend rebuild
that needs browser verification — not something to restructure blind at the tail of an audit.
Three directions proposed to the user (see 06-plan.md Track D + the AskUserQuestion in the
session). Implementation deferred until a direction is chosen.

### Option A — Clarify & de-collide (lighter, recommended first)
Keep both systems; remove the collision. "Gig" = ONLY the optional paid gig board. Strip
gig-mode jargon from mandatory-task create/edit. Merge the parent's two approval screens into
ONE queue + fix the badge to count both. Fix the non-bonus-points-zeroed trap. Drop/clarify the
"$1 MXN" framing. Lower risk, kills most of the confusion.

### Option B — Full unification (heavier)
One "Work" model with a type (chore vs gig), one create flow, one kid list, one approval queue.
Cleanest long-term; largest rebuild + migration; reverses the deliberate d42c479 split.

### Option C — Approval queue + badge only (smallest slice)
Unify just the two parent approval screens + the dashboard badge. Smallest high-value win;
leaves the create-side jargon collision.

## Other budget UX (from audit, not yet done)
- No way to create the FIRST account from the add-transaction/empty flows (buried in Settings).
- Nav is triple-fragmented (3 tabs + 13-item drawer + receipt icon + FAB + bottom nav).
- "Ready to Assign" allocation entry is unlabeled; Reports "Budget vs Actual" is a permanent
  "Coming soon"; edit flows hard-reload (`location.reload`).
These are mechanical-to-medium; bundle with the chosen task/gig direction.
