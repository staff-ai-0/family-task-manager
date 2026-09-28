# UX-C1 — Teen Home (swipe deck) + New-Gig Notifications — Design

**Date:** 2026-09-28
**Status:** approved in chat (2026-09-28), pending written-spec review
**Program:** UX/GUI/engagement program, sub-project **C1** (C = "Today" home screens; C1 = teen first)
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` (F9, F10, patterns 1–3); visual mockups `teen-home-layout.html` (option C chosen) and `teen-home-v2.html` (approved) in the brainstorm session.

## Who and why

- **Users:** TEEN role, ages 13–14. The owner's real family is 2 PARENT + 2 TEEN;
  prod overall has 3 TEEN and 3 CHILD accounts (CHILD mostly demo).
- **Problems (owner's words):** kids "open but lost" (don't know what to do
  first — too much on screen) and "bored after a while" (novelty fades).
- **Motivator:** cash (gigs + allowance) more than points.
- **Today:** a teen sees the kid dashboard tinted grey: header stuffed with
  points + cash + bank link + streak + goal, then a paragraph explaining
  points vs cash, a push button, payday, boss battle, a baby-stage pet nudge,
  and only then today's chores.

**Goal:** the first screen a teen sees answers "what do I do now, and what do
I get for it" — one task at a time, one gesture to complete, extra cash one
glance away — in a teen visual register.

**Not in C1:** levels/badges/weekly challenge (sub-project D), CHILD skin of
this layout (later C slice), parent hub (C2), any change to economy rules,
approval logic or payout math.

## Screen (approved mockup v2)

Top to bottom, mobile first (desktop = same column, max-w-md centered):

1. **Header** (dark ink `#1E2230`, not the kid sky blue): "Hola, {name}",
   cash pill (`user.cash_cents` → "$120"), and the **weekly pay meter** when
   the teen is in chore-paycheck mode — same condition as `bank.astro`
   (`paycheck.mode === "chore_proportional" && paycheck.cap_cents > 0`):
   "💵 Pago de la semana · meta $250" + the three-segment bar (green `pct`,
   red `discounted_pct`, grey rest) + "N/M hoy". **No moving dollar figure**
   (binding rule from `2026-07-21-teen-paycheck-meter-redesign-design.md`).
   Not in chore mode → no meter; the "N/M hoy" count moves next to the deck
   label.
2. **Deck** ("Tus tareas · 1 de 4"): stacked cards, top card interactive.
   Card: chips (Atrasada · ayer / +N pts / 📷 requiere foto / Bonus), title,
   one-line context ("Cuenta para tu pago de la semana" when in chore mode),
   two buttons "← Después" and "Hecho →". Progress dots under the deck.
3. **"Gana extra"** row: horizontal scroll of active gigs the teen may claim,
   max 6, each showing title and `$pesos`, **Nuevo** chip when posted within
   the last 48 h, "ver todos ›" → `/gigs`. Under the row: a one-line
   "🔔 Avísame de gigs nuevos" push opt-in (EnablePushButton, only rendered
   by the component's own rules — hidden if already subscribed/unsupported).
4. **Tiles row**: 🎯 savings goal (`/api/bank/goals/me`: name, `$saved /
   $target`, thin bar; no goal → "Elige una meta →" linking `/bank`) and
   🏆 Family Cup (`/api/family-cup/`: teen's rank this week + boss HP), linking
   `/family-cup`.
5. Bottom nav unchanged.

**Removed from the teen home** (still reachable): pet nudge (More → Mascota),
"How points & cash work" explainer paragraph (help/tour), "Abrir Mi Banco"
link (cash pill and goal tile link to `/bank`), trust-streak card, payday
surface (lives on `/bank`), star mode (CHILD-only feature).

Kept as-is on the teen page: email-verification banner, module-off banner,
flash messages, welcome/module tours (`data-tour="today-tasks"` moves onto the
deck container).

## Deck behavior

**Order** (pure function, `lib/teenDeck.ts` → `buildTeenDeck(progress)`):
1. Overdue required assignments (`progress.overdue_assignments`), grouped per
   template exactly like the current kid page (one card per template, ×N
   badge, completing it completes the **oldest** instance), oldest first.
2. Today's required assignments with `status === "pending"`, in API order.
3. Bonus assignments with `status === "pending"` if `progress.bonus_unlocked`;
   otherwise, when any bonus exists, **one locked card** ("🔒 Termina las de
   hoy · {n} bonus") that has no Hecho action.

Completed / awaiting-approval assignments are not in the deck; they count
toward "N/M hoy" (`required_completed/required_total`).

**Interactions** (client script in `components/teen/TeenHome.astro`):
- Pointer drag on the top card (touch + mouse); release past 30% of card width
  = action (right → Hecho, left → Después), else spring back.
- Buttons "← Después" / "Hecho →" do the same; ←/→ keys when the deck has
  focus. Buttons are real `<button>`s with accessible names.
- **Después**: move card to the back of the deck in this page session (client
  only, nothing persisted). A deck of one card: Después is disabled.
- **Hecho**:
  - If the card's assignment `template_requires_proof` or is a bonus task →
    open the existing proof flow (the same photo upload + note used on the
    kid page, `/api/assignments/proof-upload` + complete with proof) before
    completing. Cancel → card springs back.
  - Else → `POST /api/assignments/complete` (existing proxy) with the
    assignment id (oldest instance for grouped overdue cards).
  - Success → card flies off, counts/meter update from the response or a
    re-fetch of progress; failure → card springs back and a toast shows the
    error (existing `lib/toast.ts`).
- **Deck empty** (no cards left): celebration — confetti burst (existing
  implementation moved to `lib/celebrate.ts`, no-op under
  `prefers-reduced-motion`) + `navigator.vibrate(30)` when available — then
  "¡Día completo!", "Bonus desbloqueado" if `bonus_unlocked` flipped true,
  and the "Gana extra" row moves up into the deck's place.
- Deck empty on page load with nothing due → "Nada pendiente hoy" + gigs row
  in the deck's place (no celebration on load).

## New-gig notifications (backend)

A gig becomes visible on the board in three places in
`backend/app/services/gig_offering_service.py`:
1. `create()` — parent posts a gig (active + approved by default);
2. `review_proposal(approve=True)` — parent approves a kid proposal;
3. `update()` with `implicit_approval` — parent edits a pending proposal,
   which approves it.

After the commit in each of those paths, call one new helper
`GigOfferingService._notify_gig_published(db, offering, actor_id)`:

- **Recipients:** users in `offering.family_id` who are participating members
  (`TaskAssignmentService._participating_member_clause()` — active AND
  parent-approved), whose role is in `offering.allowed_roles` when set, else
  role in {TEEN, CHILD}; excluding `actor_id` and excluding
  `offering.created_by` (a proposer already gets "propuesta aprobada").
- **Notification:** new type `NotificationType.GIG_PUBLISHED = "gig_published"`,
  new copy key `gig_published`: title "💵 Nuevo: {title}" / "💵 New: {title}",
  body "${pesos} MXN · tócalo para apartarlo" / "${pesos} MXN · tap to claim",
  link `/gigs`, per-recipient (`user_id` set), push on (existing
  `create_localized` path, which also respects the 10-per-hour push cap).
- **Best-effort:** wrapped so any notification failure is logged and never
  fails or rolls back the gig post (same pattern as the existing proposal
  notifications).
- Not superseding (not in `SUPERSEDING_TYPES`); counts in the 14-day badge.

## Units and files

| File | Responsibility |
|------|----------------|
| `frontend/src/lib/teenDeck.ts` (new) | `buildTeenDeck(progress)`, `isNewGig(gig, now)`, `payMeterView(paycheck)` — pure, vitest-covered |
| `frontend/src/lib/celebrate.ts` (new) | confetti burst + haptic; moved out of `dashboard.astro` (kid page keeps using it) |
| `frontend/src/components/teen/TeenHome.astro` (new) | teen home markup + deck client script |
| `frontend/src/pages/dashboard.astro` | teen branch renders `TeenHome` with fetched data; extra fetches only for teens (paycheck, bank goal, gigs); kid branch unchanged except importing `celebrate` |
| `frontend/src/components/EnablePushButton.astro` | optional `label` prop for the gigs-row opt-in copy |
| `backend/app/models/notification.py` | `GIG_PUBLISHED` constant |
| `backend/app/services/notification_service.py` | `gig_published` copy |
| `backend/app/services/gig_offering_service.py` | `_notify_gig_published` + three call sites |

## Error handling

- Every extra teen fetch is fail-open (apiFetch never throws): missing
  paycheck → no meter; missing goal → "Elige una meta"; missing gigs → row
  hidden; missing family cup → tile hidden.
- Deck actions never leave a card half-removed: the card is removed only on a
  2xx; otherwise it springs back with a toast.
- Proof upload failure keeps the sheet open with the error, like today.

## Testing

- **vitest** (`frontend/test/teen-deck.test.ts`): overdue grouping + oldest
  instance id; required order; bonus unlocked vs locked card; completed and
  awaiting-approval excluded; N/M counts; `isNewGig` 48 h boundary (47 h
  yes, 49 h no, missing timestamp no); `payMeterView` shown only for
  `chore_proportional` with cap > 0, segment widths clamp to 0–100 and never
  sum past 100. Every test mutation-checked.
- **pytest** (`backend/tests/test_gig_published_notifications.py`): create →
  teens+children notified, parents/actor not; `allowed_roles=["teen"]` →
  only teens; inactive / pending-approval members skipped; other families
  never notified; proposal approved via review and via implicit update →
  proposer skipped, others notified; notification failure (patched raise)
  → offering still created/approved.
- `astro check` + `astro build`; manual pass on prod as the demo teen after
  deploy (swipe right/left, proof sheet, empty-deck celebration, gig row
  "Nuevo", push opt-in visibility).

## Rollout

One PR → CI → merge → `deploy-onprem.sh` (no migration: new notification type
is a string constant on a `String(48)` column) → verify on prod as
`diego.demo` (TEEN) and that `sofia.demo` (CHILD) still gets the old kid
dashboard. New-gig notification check is the ONLY prod write: post one
clearly named test gig ("Prueba UX-C1") in the **demo** family as the demo
parent, confirm `diego.demo` gets "💵 Nuevo", then archive the gig. Never in
the owner's real family.
