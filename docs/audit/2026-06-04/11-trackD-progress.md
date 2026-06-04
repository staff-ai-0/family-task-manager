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

### Option A — Clarify & de-collide (CHOSEN by user) — IN PROGRESS
- [x] **Part 1 — chore-create de-collide** (commit 88c45fb, astro build passes):
  - Gig-mode dropdown now hidden unless "Bonus task" is toggled (no gig jargon in plain chores).
  - Non-bonus points no longer silently 0 — visible Points input (default 10) used in the payload.
- [x] **Part 2 — unify parent approval** (commits 1881272, astro build passes):
  - `/parent/approvals` now shows BOTH sources in one queue — chore/bonus task proofs
    (`/api/task-assignments/pending-approvals`) + gig-board claim proofs
    (`/api/gigs/claims/pending-approvals`), each section with the correct approve/reject call.
  - Dashboard badge (`parent/index.astro`) summed only task approvals → now sums both sources
    (was the "badge misses half" finding).
  - Interactive approve/reject reuses the proven `/parent/gigs` fetch pattern; **browser
    click-through still recommended** before merge (build verifies compile, not runtime clicks).
- [ ] **Optional polish (low priority):** the `/parent/gigs` page still has a redundant
  "pending" tab that duplicates the unified `/parent/approvals` queue. Point it at `/approvals`
  (remove the tab's list + approve JS) for full single-queue cleanliness. Left undone to avoid a
  blind restructure of the tabbed 358-line page.
- [ ] Optional: drop/clarify the "1 pt = $1 MXN" framing where no cash payout exists.

**Option A is functionally complete** — the chore/gig UI collision (jargon, silent points,
split approvals, wrong badge) is resolved. Remaining items are polish.

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
