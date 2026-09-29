# UX-C1 — Swipe-Deck Home for Everyone + New-Gig Notifications — Design

**Date:** 2026-09-28
**Status:** approved in chat (2026-09-28; scope widened to all roles the same day), pending written-spec review
**Program:** UX/GUI/engagement program, sub-project **C1** of C ("Today" home screens)
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` (F8, F9, F10, competitor patterns 1–3); brainstorm mockups `teen-home-layout.html` (option C "swipe deck" chosen) and `teen-home-v2.html` (approved).

## Who and why

- **Owner's real family:** 2 PARENT + 2 TEEN (ages 13–14). Prod overall: 3 TEEN, 3 CHILD (mostly demo), 8 PARENT.
- **Problems (owner's words):** kids "open but lost" (don't know what to do first — too much on screen) and "bored after a while".
- **Motivator:** cash (gigs + allowance) more than points.
- **Today:** teens get the kid dashboard tinted grey; the header is stuffed (points, cash, bank link, streak, goal), then an explainer paragraph, a push button, payday, boss battle, a baby-stage pet nudge — today's chores are below the fold. Parents see their own chores as a small list on `/parent`.

**Goal:** every member's "what do I do now" is one card, one gesture. Kids also see what they earn (pay meter, extra cash from gigs) at a glance.

**Scope — everyone gets the deck:**
- **TEEN** and **CHILD** → new kid home at `/dashboard` (same layout, two skins).
- **PARENT** → the "Mis tareas de hoy" list on `/parent` becomes the same deck (compact: no pay meter, no gigs row). The rest of `/parent` is unchanged (the parent hub redesign is C2).

**Not in C1:** levels/badges/weekly challenge (D), parent hub (C2), dark mode / design-system cleanup (B), any change to economy rules, approval logic or payout math.

## Kid home (`/dashboard`, TEEN + CHILD)

Approved mockup v2, top to bottom (mobile first; desktop = same column, max-w-md centered):

1. **Header** — "Hola, {name}" and a balance pill, plus the **weekly pay meter** when the kid is in chore-paycheck mode (same condition as `bank.astro`: `paycheck.mode === "chore_proportional" && paycheck.cap_cents > 0`): "💵 Pago de la semana · meta $250", the three-segment bar (green `pct`, red `discounted_pct`, grey rest) and "N/M hoy". **No moving dollar figure** — binding rule from `2026-07-21-teen-paycheck-meter-redesign-design.md`. Not in chore mode → no meter; "N/M hoy" moves to the deck label.
   - Balance pill: cash (`user.cash_cents`, "$120"); in **star mode** (CHILD) it shows ⭐ points instead.
2. **Routines strip** (from UX-A) — unchanged, above the deck, only when the member has routines today.
3. **Deck** ("Tus tareas · 1 de 4") — see *Deck* below.
4. **"Gana extra"** — horizontal row of active gigs the member may claim, max 6: title, `$pesos`, **Nuevo** chip when posted in the last 48 h; "ver todos ›" → `/gigs`. Under it a one-line "🔔 Avísame de gigs nuevos" push opt-in (EnablePushButton, rendered only by its own rules). Hidden when the gigs module is off.
5. **Tiles row** — 🎯 cash savings goal (`/api/bank/goals/me`: name, `$saved / $target`, thin bar; none → "Elige una meta →" to `/bank`) and 🏆 Family Cup (`/api/family-cup/`: member's rank this week + boss HP) → `/family-cup`. **CHILD only:** a third 🐾 pet tile (mood + "Cuidar" → `/pet`) when the pet module is on.

**Skins:**
- **TEEN:** dark ink header (`#1E2230`), neutral chips, fewer emoji.
- **CHILD:** current kid sky header, brighter chips, same structure.

**Removed from the kid home** (still reachable): points/cash explainer paragraph (help + tour), "Abrir Mi Banco" link (pill and goal tile link to `/bank`), trust-streak card, payday surface (lives on `/bank`), pet nudge for TEEN (More → Mascota). Kept: email-verification banner, module-off banner, flash messages, tours (`data-tour="today-tasks"` moves onto the deck).

## Parent's own chores (`/parent`)

The existing "Mis tareas de hoy" section keeps its position and heading but renders the **compact deck**: same cards, same actions, no pay meter, no gigs row, no tiles. Empty → "Nada pendiente hoy" (no celebration on load). Everything else on `/parent` is untouched.

## Deck (shared component)

**Order** — pure function `buildDeck(progress)` in `frontend/src/lib/deck.ts`:
1. Overdue required assignments (`progress.overdue_assignments`), grouped per template like today's kid page (one card per template, ×N badge; completing it completes the **oldest** instance), oldest first.
2. Today's required assignments with `status === "pending"`, in API order.
3. Bonus assignments with `status === "pending"` if `progress.bonus_unlocked`; otherwise, when any bonus exists, **one locked card** ("🔒 Termina las de hoy · {n} bonus") without a Hecho action.

Completed / awaiting-approval assignments are not cards; they count toward "N/M hoy" (`required_completed/required_total`).

**Card:** chips (Atrasada · ayer / +N pts / 📷 requiere foto / Bonus), title, one-line context ("Cuenta para tu pago de la semana" when the kid is in chore mode), buttons "← Después" and "Hecho →". Progress dots below.

**Interactions** — `frontend/src/components/deck/TaskDeck.astro` (markup + client script), used by the kid home and `/parent`:
- Pointer drag on the top card (touch + mouse). Release past 30% of the card width = action (right → Hecho, left → Después); otherwise spring back.
- The buttons do the same, and so do ←/→ when the deck has focus. Buttons are real `<button>`s with accessible names.
- **Después:** move the card to the back of the deck for this page session (client only, nothing persisted). Disabled when one card is left.
- **Hecho:**
  - If the assignment `template_requires_proof` or is a bonus task, open the existing proof flow (photo upload + note, `/api/assignments/proof-upload` then complete with proof) first. Cancel → spring back.
  - Else `POST /api/assignments/complete` (existing proxy) with the assignment id (oldest instance for grouped overdue cards).
  - 2xx → card flies off and counts/meter update (re-fetch progress). Failure → spring back + toast (`lib/toast.ts`).
- **Deck emptied by the member:** celebration — confetti (existing implementation moved to `frontend/src/lib/celebrate.ts`, no-op under `prefers-reduced-motion`) + `navigator.vibrate(30)` when available — then "¡Día completo!", "Bonus desbloqueado" when `bonus_unlocked` flipped true, and on the kid home the "Gana extra" row moves into the deck's place.
- **Empty on load:** "Nada pendiente hoy" (kid home: gigs row in the deck's place), no celebration.

## New-gig notifications (backend)

A gig becomes visible on the board in three places in `backend/app/services/gig_offering_service.py`:
1. `create()` — parent posts a gig (active + approved by default);
2. `review_proposal(approve=True)` — parent approves a kid proposal;
3. `update()` with `implicit_approval` — parent edits a pending proposal, which approves it.

After the commit in each path, call one new helper `GigOfferingService._notify_gig_published(db, offering, actor_id)`:
- **Recipients:** users in `offering.family_id` who are participating members (`TaskAssignmentService._participating_member_clause()` — active AND parent-approved), whose role is in `offering.allowed_roles` when set, else role in {TEEN, CHILD}; excluding `actor_id` and `offering.created_by` (a proposer already gets "propuesta aprobada").
- **Notification:** new type `NotificationType.GIG_PUBLISHED = "gig_published"`; new copy key `gig_published` — title "💵 Nuevo: {title}" / "💵 New: {title}", body "${pesos} MXN · tócalo para apartarlo" / "${pesos} MXN · tap to claim"; link `/gigs`; one per recipient (`user_id` set); push via the existing `create_localized` path (respects the 10-per-hour push cap).
- **Best-effort:** any failure is logged and never fails or rolls back the gig post (same pattern as the existing proposal notifications).
- Not a superseding type; counts in the 14-day badge like others.

## Units and files

| File | Responsibility |
|------|----------------|
| `frontend/src/lib/deck.ts` (new) | `buildDeck(progress)` — pure, vitest-covered |
| `frontend/src/lib/kidHome.ts` (new) | `isNewGig(gig, now)`, `payMeterView(paycheck)`, `claimableGigs(offerings, role)` — pure, vitest-covered |
| `frontend/src/lib/celebrate.ts` (new) | confetti + haptic, moved out of `dashboard.astro` |
| `frontend/src/components/deck/TaskDeck.astro` (new) | deck markup + swipe/button/keyboard script + proof hand-off; props: `cards`, `lang`, `variant` (`full` \| `compact`), `choreMode` |
| `frontend/src/components/home/KidHome.astro` (new) | kid home layout (header, meter, routines strip, deck, gigs row, tiles); prop `skin` (`teen` \| `child`) |
| `frontend/src/pages/dashboard.astro` | renders `KidHome` for TEEN and CHILD with the fetched data; the old kid markup it replaces is deleted, not kept behind a flag |
| `frontend/src/pages/parent/index.astro` | "Mis tareas de hoy" renders `TaskDeck variant="compact"` |
| `frontend/src/components/EnablePushButton.astro` | optional `label` prop for the gigs-row opt-in copy |
| `backend/app/models/notification.py` | `GIG_PUBLISHED` constant |
| `backend/app/services/notification_service.py` | `gig_published` copy |
| `backend/app/services/gig_offering_service.py` | `_notify_gig_published` + three call sites |

The proof flow (photo upload modal + submit) currently lives inline in `dashboard.astro` and `/parent`: it moves into `TaskDeck` (one copy) as part of this change.

## Error handling

- Every extra fetch is fail-open (apiFetch never throws): no paycheck → no meter; no goal → "Elige una meta"; no gigs → row hidden; no family cup → tile hidden; no pet → tile hidden.
- Deck actions never leave a card half-removed: a card is removed only on a 2xx; otherwise it springs back with a toast.
- Proof upload failure keeps the sheet open with the error, as today.

## Testing

- **vitest:**
  - `frontend/test/deck.test.ts`: overdue grouping + oldest instance id; required order; bonus unlocked vs locked card; completed and awaiting-approval excluded; N/M counts.
  - `frontend/test/kid-home.test.ts`: `isNewGig` 48 h boundary (47 h yes, 49 h no, missing timestamp no); `payMeterView` only for `chore_proportional` with cap > 0, segment widths clamped 0–100 and never summing past 100; `claimableGigs` honors `allowed_roles`, active only, max 6.
  - Every test mutation-checked.
- **pytest** (`backend/tests/test_gig_published_notifications.py`): create → teens + children notified, parents and actor not; `allowed_roles=["teen"]` → only teens; inactive / pending-approval members skipped; other families never notified; proposal approved via review and via implicit update → proposer skipped, others notified; notification failure (patched raise) → offering still created/approved.
- `astro check` + `astro build`.
- Manual on prod after deploy: demo TEEN (`diego.demo`), demo CHILD (`sofia.demo`) and demo PARENT — swipe right/left, buttons, keyboard, proof sheet, empty-deck celebration, gigs row "Nuevo", push opt-in visibility, parent compact deck.

## Rollout

One PR → CI → merge → `deploy-onprem.sh` (no migration: the new notification type is a string constant on a `String(48)` column) → the manual checks above. The new-gig notification check is the **only prod write**: post one clearly named test gig ("Prueba UX-C1") in the **demo** family as the demo parent, confirm the demo teen and child get "💵 Nuevo", then archive the gig. Never in the owner's real family.

## Plan-time refinements (2026-09-28)

Recorded in the plan (`docs/superpowers/plans/2026-09-28-ux-c1-deck-home.md`):
counts update client-side after each completion, while the pay meter and a
newly unlocked bonus refresh on reload (celebration offers "Ver bonus");
the kid page splits into `KidHeader` (header slot) + `KidHome` (body);
prior-day gigs awaiting a decision survive as a "⏳ N en revisión" chip;
payday card and GigsIntroBanner leave `/dashboard`; star-mode children use the
points goal and see no gigs row; `/api/assignments/complete` gains a JSON mode
for the deck (form mode unchanged).
