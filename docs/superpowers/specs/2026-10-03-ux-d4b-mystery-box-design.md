# UX-D4b — Mystery Box — Design

**Date:** 2026-10-03
**Status:** design approved in conversation 2026-10-03 (four questions + three design parts); awaiting written-spec review
**Program:** UX/GUI program, the last piece of D (progression & engagement loop). D1 streak + rank, D2 badges, D3 weekly quest, D4a pings and the Jarvis teen check-in have shipped.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` (row D and pattern 3: "mystery-reward reveal" — a reveal is what kids keep coming back for; the content can vary, the moment must be reliable).
**Builds on:** `docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md` (perfect day), `docs/superpowers/specs/2026-10-01-ux-d3-weekly-quest-design.md` (three-state family setting, created-and-paid-on-read, pay-once).

## Goal

Give a kid a *reveal* for finishing the day: a closed box that appears the moment the last chore is done and opens to a surprise. The work that earns it is predictable (a perfect day); only what is inside varies. Real surprises come from the parents' jar; points are the fallback so there is always something to open.

**Decisions (user, 2026-10-03):**
- Inside the box: a parent-written surprise from the family's jar when the jar has any; a points bonus when it does not. (Q1 c)
- The box appears on a **perfect day** — every non-bonus chore of the day done — at most one per kid per day. No perfect-week box, no random drops per chore. (Q2 a)
- Jar surprises are **reusable**: a list the parent writes once; the box picks one at random, never yesterday's. (Q3 a)
- Same opt-in as the weekly quest: existing families start undecided (off + one-time parent-hub card); new families start on with the points fallback. (Q4 a)

**Not in D4b:** a perfect-week box, single-use tickets, random drops per chore, pushes about boxes (D4a's one-reminder-a-day rule stands), parent-chosen odds, surprises aimed at one kid, a box for parents, pet effects.

## Rules

### Who and when

Kids and teens (`KID_ROLES`). "Today" and "the day" are the family's (`families.timezone`).

A **perfect day** is the streak's rule for a day in state `done` (`ProgressService.day_states` → `DayState.done` for today): the kid has at least one non-bonus, non-cancelled assignment dated today, and every one of them is `COMPLETED`, not graded `missed`, not rejected, with `completed_at` on or before the assigned date (legacy rows without a timestamp count). Chores awaiting parent review count — the box must appear the moment the kid finishes, like the streak. A later rejection does not take an opened box back.

A day with no chores, or with only bonus tasks, gives no box.

One box per kid per day: `UNIQUE(family_id, user_id, day)`. A box is created the first time the kid's progress is read on or after a perfect day — today's, and yesterday's when that day was perfect and has no box yet (a day finished from the pet page or marked done by a parent, first read after midnight). Older days are never backfilled (created on read, like the quest; amended after the final review). It never expires: an unopened box waits, and several unopened ones are shown together ("×2").

### Opening

The content is decided **when the box is opened**, not when it appears:

1. If the family's jar has at least one surprise, pick one at random, excluding the surprise this kid got in their most recent opened box (when the jar has two or more). Copy its title and emoji onto the box (`kind = surprise`).
2. Otherwise `kind = points`: a random whole number from `max(1, M // 4)` to `M`, where `M = families.mystery_box_points`; paid once into the points ledger as a `bonus` `PointTransaction` ("Caja sorpresa" / "Mystery box") in the same commit, through the quest's pay-once pattern (guarded `UPDATE … WHERE opened_at IS NULL RETURNING`, locked user row, `db.refresh(kid)` before adding).

A box can only be opened by the kid it belongs to, in a family whose boxes are on (`mystery_box_points > 0`). In a family that switched off, an unopened box cannot be opened (`409`) and waits; if the family turns boxes on again it opens then.

### Parents

- **Surprises to deliver.** A revealed surprise lands on the parent home: "Diego — *Pick dessert tonight* 🍨 (today)" with "Delivered ✓", which stamps `delivered_at` / `delivered_by`. Points need nothing.
- **Settings → Family → Mystery box.** The points maximum (`0` turns boxes off; `1–500`), and the jar: up to 20 active surprises, each a title (1–60 characters, trimmed) and an optional emoji (≤ 4 characters); add and remove any time. Removing a surprise never touches opened boxes (they keep their copy).
- **`families.mystery_box_points`** — nullable integer, default 20 for families created after the migration; the migration resets every existing family to `NULL`:
  - `NULL` — undecided: boxes off; the parent hub shows a one-time card "New: the mystery box" with "Turn on (surprises or up to 20 points)" / "Not now" and a link "Fill the jar" to the settings section. `Turn on` writes 20, `Not now` writes 0.
  - `0` — off by choice. · `> 0` — on, with that points maximum.

### Copy (kid side, ES / EN — lives only in `frontend/src/lib/mystery.ts`)

| State | ES | EN |
|---|---|---|
| closed | "🎁 ¡Una caja sorpresa! Toca para abrir" (+ " ×N" when N > 1 wait) | "🎁 A mystery box! Tap to open" (+ " ×N") |
| opening | "Abriendo…" | "Opening…" |
| revealed, surprise | "Te tocó: *{title}* {emoji} — ¡pídesela a tus papás!" | "You got: *{title}* {emoji} — ask your parents!" |
| revealed, points | "+{n} puntos" (star mode: "+{n} ⭐") | "+{n} points" (star mode: "+{n} ⭐") |

Parent copy: "Por entregar" / "To deliver", "Entregada ✓" / "Delivered ✓", "Caja sorpresa" / "Mystery box", "Frasco de sorpresas" / "Surprise jar".

## Architecture

**Backend**
- `backend/app/models/mystery.py`: `MysterySurprise` (`mystery_surprises`: `id, family_id, title, emoji, created_by, created_at` — removed rows are deleted outright; opened boxes keep their copied title) and `MysteryBox` (`mystery_boxes`: `id, family_id, user_id, day, kind, surprise_id (SET NULL), surprise_title, surprise_emoji, points, opened_at, delivered_at, delivered_by, created_at`; `UNIQUE(family_id, user_id, day)`; CHECKs: `kind IS NULL OR kind IN ('surprise','points')`, `(opened_at IS NULL) = (kind IS NULL)`, `points >= 0`). Both tables join `EXPORTED_FAMILY_TABLES` (`progress/mystery_surprises.json`, `progress/mystery_boxes.json`).
- Migration `mystery_box` (down-revision `teen_checkins`): the two tables and `families.mystery_box_points` (`ADD COLUMN … DEFAULT 20` then `UPDATE families SET mystery_box_points = NULL`, the quest's opt-in trick).
- `backend/app/services/mystery_service.py`: pure `points_for(max_points, rng)`, `pick_surprise(surprises, last_surprise_id, rng)`; `MysteryService.sync(db, user)` (creates today's box when the day is perfect; returns the view), `open(db, user, box_id)`, `deliveries(db, family_id)`, `mark_delivered(db, parent, box_id)`, jar `list / add / remove`.
- Routes: `GET /api/progress/mystery`, `POST /api/progress/mystery/{id}/open` (kid/teen; `applies: false` for parents), `GET /api/progress/mystery/deliveries`, `POST /api/progress/mystery/{id}/delivered` (parent), `GET / POST /api/families/surprises`, `DELETE /api/families/surprises/{id}` (parent). `FamilyUpdate.mystery_box_points` (`ge=0, le=500`), `FamilyResponse.mystery_box_points: Optional[int]`.
- No LLM call; no scheduled job; no notification.

**Frontend**
- `frontend/src/lib/mystery.ts`: copy, `mysteryView(resp, lang, starMode)`, `mysteryDomUpdate(view, lang)` (pure, like the quest), request helpers.
- `frontend/src/components/home/MysteryBoxCard.astro`: one card, three states by `hidden` attribute; opening = short shake + `fireConfetti`; refetches on `ftm:deck-empty` so the box appears the moment the last chore is done. Rendered by `KidHome` under the task deck, next to the quest card; `dashboard.astro` fetches `/api/progress/mystery` for kids and teens.
- `frontend/src/pages/parent/index.astro`: "To deliver" strip (hidden when empty) + the opt-in card. `parent/settings/family.astro`: `#mystery-section` with the points field and the jar.
- Astro route files exist for every path the browser calls (`/api/progress/[...path].ts` and `/api/families/*` — check `surprises` is routed; add a file if not), with the guard test from D4a.

**Docs:** guides EN/ES 17.5.6 "Mystery box"; `CLAUDE.md` Progress row.

## Error handling

- Progress read failing → no card. Open failing → toast, the box stays closed. A 409 (family off) → toast "Boxes are off right now".
- Double open: the guarded UPDATE makes the second call read the already-opened box (200, same content), never a second payment.
- A deleted jar surprise: opened boxes keep their copied title; it simply stops being picked.
- Kid or family deleted: rows cascade.

## Testing

Backend: pure rules (points range at several maxima, including `M = 1..3`; pick excludes the last one when the jar has ≥ 2 and allows it when the jar has 1); service against the DB (perfect day creates one box and only one; bonus-only or no-chore day creates none; opening pays once under two concurrent-style calls; empty jar → points within range and a `bonus` transaction; jar → surprise copied, no points; never yesterday's surprise; a kid cannot open a sibling's or another family's box; a family at 0/NULL cannot open; parent delivery flow and isolation; jar limits 20 / 60 chars / trimming); family setting three-state + migration test (DEFAULT 20 then reset to NULL); export registry guard.

Frontend (vitest): `lib/mystery.ts` views; source checks for the card, KidHome/dashboard wiring, hub strip + card, settings section; route-file guard; existing visual / dialog guards.

## Rollout and production check

Deploy with `./scripts/deploy-onprem.sh`. Existing families start undecided. Demo family only (`b8312b5a-c9c0-469f-992f-8dbd412db4a7`, verified by id): mariana — hub card → Turn on, add two surprises; sofia — finish today's chores → box appears → open → reveal; mariana — "To deliver" row → Delivered ✓; sofia — second open returns the same box, no second payment. Leave the demo family on.
