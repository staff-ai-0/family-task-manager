# UX-C2 — Parent "Today" Hub — Design

**Date:** 2026-09-28
**Status:** layout + technical design approved in chat (2026-09-28), pending written-spec review
**Program:** UX/GUI/engagement program, sub-project **C2** of C ("Today" home screens). C1 (kid swipe-deck home, PR #276) shipped.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` F8 ("parent home is a nav grid, not a 'what needs me now' screen"); brainstorm mockup `parent-hub-v1.html` (approved: "go").

## Who and why

- **Today `/parent`** stacks, top to bottom: gigs intro banner, push button, boss bar, the parent's own chores deck (C1), payday banner, AI-consent card, onboarding checklist, money owed, **10 navigation tiles** (every one also in the More sheet or bottom nav), and **per-kid cards at the very bottom**. Pending approvals are only a small badge on one tile.
- **What a parent opens the app to do (owner's answer, in order):** review kids' work → see how the kids are doing → pay the kids → money/budget.

**Goal:** the first screen answers "what needs me now", in that order, and lets the parent act on the common case without leaving home.

**Decisions from the brainstorm:**
- Review: the **3 oldest** pending items inline with full actions; "Ver todas (N)" → `/parent/approvals`.
- Kids: one row per kid with a **nudge** button, **capped** (1 per kid per 3 h, shared by both parents).
- Clutter: the tile grid goes; intro cards collapse into **one setup card** shown until setup is done.
- Budget: a **glance card with no scan button** — the "exactly two visible scan triggers" rule (CLAUDE.md, 2026-08-11) stays intact.
- Data: **reuse existing endpoints + small additions** (not a new aggregate endpoint, not client-side section loading).

**Not in C2:** kid screens (C1 shipped), dark mode / design tokens / native dialogs (B), levels/badges (D), AI chore creation (E), any change to approval, payout or budget math, bulk approve on home (stays on `/parent/approvals`).

## Page layout (`/parent`, PARENT only)

Mobile first; desktop = same single column, `max-w-md mx-auto`. Top to bottom, each section renders only when it has content:

1. **Header** — "Hola, {first name}" / "Hi, {first name}" and today's date (family-local, e.g. "Lunes 28 sep"). Dark slate gradient as today.
2. **Banners** (unchanged): module-off, flash success, flash error.
3. **AI-consent card** — unchanged markup + handlers, shown while `family.ai_processing_consent_at == null`.
4. **Setup card** ("Configura tu familia · N de 4") — see *Setup card*.
5. **Por revisar · N** — see *Review section*. Under it, the push opt-in (`EnablePushButton`, label "🔔 Avísame cuando haya algo que revisar" / "🔔 Tell me when something needs review"). This is the page's **only** `EnablePushButton` (the top-of-page one is removed).
6. **Hoy / Today** — see *Kid rows*.
7. **Por pagar / To pay** — the existing money-owed card (`/api/bank/payout-summary`, link to `/parent/payouts`, or `/parent/settings/family-bank` when the gigs module is off). The payday banner folds in as one line inside it ("Diego recibió su pago del Banco Familiar."). Hidden when nothing is owed **and** nobody was paid in the last 2 days.
8. **Mis tareas de hoy** — the C1 compact `TaskDeck`, unchanged (same data, same condition `myHasChores`).
9. **Presupuesto · {mes}** — see *Budget glance*.
10. **Family Cup mini card** — "🏆 Family Cup · {boss name} {hp}/{max} HP" → `/family-cup`. Hidden when `/api/family-cup/` has no boss.

**Removed from `/parent`:** the 10-tile navigation grid, the per-kid oversight cards at the bottom (replaced by *Kid rows*), the standalone payday banner (folded into *Por pagar*), the top `BossBattleBar` (replaced by the mini card), the top `EnablePushButton` (moved under review), and `GigsIntroBanner` (replaced by the setup card's guide link). `GigsIntroBanner.astro` is deleted — `/parent` is its only user. The backend `acknowledged_gigs_intro` field and its ack endpoint stay untouched (harmless, no migration).

**Empty states:**
- No pending reviews → one line "✓ Nada por revisar" / "✓ Nothing to review" (no big card), opt-in still shown under it.
- No kids in the family → *Hoy* shows one line "Invita a tus hijos para ver su día aquí ›" → `/parent/members#invite`.
- Own chores empty → the C1 deck's "Nada pendiente hoy" (unchanged).

## Setup card

Replaces the onboarding widget and `GigsIntroBanner`.
- **Shown when** `onboarding` loaded AND `!onboarding.dismissed` AND `!onboarding.all_done`. (Today the widget also shows after `all_done` until dismissed; that tail is dropped — a finished family gets its home back.)
- **Content:** title "Configura tu familia · {done} de 4" / "Set up your family · {done} of 4", a progress bar, the four core steps (task, reward, invite kids, first approval) with a ✅/◻ mark and a "›" link on undone steps (same targets as today), then one line "¿Cómo funcionan puntos y dinero? **Ver guía**" → `/ayuda` (es) / `/help` (en).
- **Optional extra steps** (flyer scan, first gig) are dropped from the card — they were never part of `all_done`.
- **Dismiss:** an "×" button (accessible name "Ocultar" / "Hide") calls the existing `POST /api/families/onboarding/dismiss` and removes the card. The button keeps id `dismiss-onboarding` and the card id `onboarding-widget`; the handler moves from `parent/index.astro` into the `ParentHub` script. The AI-consent handlers stay in `parent/index.astro`.
- The "Tomar el tour" / "Abrir ayuda" buttons of the finished widget go away with the `all_done` tail.

## Review section

**Queue** — pure function `buildReviewQueue(tasks, claims, redemptions, lang)` in `frontend/src/lib/reviewQueue.ts`:
- Inputs: the three lists `/parent/approvals` already fetches — `/api/task-assignments/pending-approvals`, `/api/gigs/claims/pending-approvals`, `/api/rewards/redemptions/pending`.
- Output: `ReviewItem[]` — `{ kind: "task" | "gig" | "redemption", id, title, kidName, when: string | null (ISO), pointsLabel, proofImageUrl, proofText, allowPartial }`, sorted **oldest first** by `when` (items without a timestamp go last, stable).
- `allowPartial` = `kind === "task" && template_gig_mode !== "collaboration"` (same rule as `/parent/approvals`: partial is rejected on collaboration gigs).
- `N` in "Por revisar · N" = the queue length. It equals the sum the page already computes for the old tile badge **plus** pending redemptions (the approvals page counts redemptions too).

**Rendering** — `frontend/src/components/home/ReviewCard.astro`, one per item:
- Kid initial avatar, title, kid name + relative time ("ayer 20:14"), a chip (`+N pts` for tasks, `gig $N` for gig claims, `N pts` premio for redemptions), proof thumbnail (`{url}?size=thumb`) when present — tapping it opens the full image in a new tab.
- Buttons:
  - **task:** "✗ No hecha" · "Casi" (only when `allowPartial`) · "✓ Aprobar"
  - **gig claim:** "✗ No hecha" · "✓ Aprobar"
  - **redemption:** "✗ Rechazar" · "✓ Aprobar"
- **✓ Aprobar** decides in one tap (grade `full` for tasks).
- **Casi** expands inline: chips 25 / 50 / 75 % (50 preselected), an optional note field, and "Confirmar". Confirm sends grade `partial` with the chosen pct.
- **✗ No hecha / Rechazar** expands inline: an optional note field and "Confirmar" (tasks send grade `missed`; gig claims `approved:false`; redemptions the reject route).
- Only one card is expanded at a time; opening another collapses the first.

**Queue behavior:**
- The page renders up to **8** items; the first 3 are visible, the rest `hidden`.
- After a successful decision the card is removed, the next hidden card is revealed, and "N" decrements. A decided card is removed **only after a 2xx** — on failure it stays, its buttons re-enable and a toast shows the backend reason (`detail`/`message`, e.g. "Insufficient points…").
- **Single-flight per page:** while one decision is in flight, every review button is disabled.
- When the visible list empties and `N > 0` (more than 8 were pending), show "Quedan {N} · Ver todas ›" → `/parent/approvals`.
- When `N` reaches 0, the section swaps to "✓ Nada por revisar".
- The bottom-nav "Aprobar" badge is server-rendered; it refreshes on the next navigation (no live update).

**Shared request code** — `frontend/src/lib/approvalActions.ts`:
- `submitDecision(d: Decision): Promise<{ ok: true } | { ok: false; error: string | null }>` where `Decision = { kind, id, approve: boolean, grade?: "full" | "partial" | "missed" | null, partialPct?: number | null, notes?: string | null }`.
- Requests are exactly today's, moved out of `approvals.astro`'s `decide()`:
  - task → `POST /api/assignments/approve` `{assignment_id, approve, notes, grade, partial_credit_pct}`
  - gig → `POST /api/gigs/claims/{id}/approve` `{approved, notes}`
  - redemption → `POST /api/rewards/redemptions/{id}/{approve|reject}` `{notes}`
- `/parent/approvals` switches its `decide()` to call `submitDecision` (DOM removal and its batch buttons stay in the page). Its markup does not change.

## Kid rows

**Data:**
- `GET /api/oversight/summary` (existing) with five new `KidSummary` fields (see *Backend*).
- `GET /api/bank/chore-paycheck/{kid_id}` per kid, fetched in parallel (families have few kids), for the pay meter.

**View** — pure `kidRowView(kid, paycheck, now)` in `frontend/src/lib/parentHub.ts`:
- `doneLabel` "{done}/{total} hoy" / "{done}/{total} today" from `required_done_today` / `required_total_today` (hidden when total is 0 and nothing overdue).
- `overdueChip` "{n} atrasada(s)" / "{n} overdue" when `overdue_count > 0`.
- Pay meter = C1's `payMeterView(paycheck)` (`frontend/src/lib/kidHome.ts`, reused as is): shown only for `chore_proportional` with `cap_cents > 0`; green/red/grey bar, **no dollar figure** (same rule as the kid's own meter).
- When the meter is not shown, a plain progress bar of done/total.
- Goal line: points goal from `kid.goal` ("🎯 {reward} · {pct}%", "🎯 {reward} · ¡lista!" when affordable). Hidden when none.
- `nudge` state:
  - Let `open = required_open_today + overdue_count`.
  - `"done"` → "✓ Listo" / "✓ Done" when `required_total_today > 0` and `open == 0`.
  - `"none"` → no button when `required_total_today == 0` and `open == 0`.
  - `"cooldown"` → greyed "Enviado · hace {h} h" / "Sent · {h} h ago" when `last_nudged_at` is within 3 h of `now` (`{h}` = whole hours, "hace menos de 1 h" under 1 h).
  - `"ready"` → "⏰ Recordar" / "⏰ Remind" (when `open > 0` and not in cooldown).
  - Cooldown only applies when `open > 0`; a kid with nothing open shows "done"/"none" regardless of `last_nudged_at`.
- Row tap (outside the button) → `/parent/day`.

**Rendering** — `frontend/src/components/home/KidRow.astro`. Nudge click: `POST /api/oversight/nudge/{kid_id}` → on 2xx button becomes the cooldown state ("Enviado · ahora" / "Sent · just now") + toast "Recordatorio enviado a {name}"; on 429 cooldown state with the server's retry time; on 409 "Nada pendiente para {name}" toast and the button hides; other failures toast and re-enable.

## Budget glance

- **Shown when** the budget module is on for the family (`user.enabled_modules == null || includes("budget")`) **and** the month fetch succeeded **and** the month has any budgeted amount or any activity.
- **Data:** `GET /api/budget/month/{year}/{month}` (family-local current month) `totals` and `GET /api/budget/receipt-drafts/` (count of pending drafts).
- **View** — pure `budgetGlanceView(totals, draftsCount)` in `parentHub.ts`: `spent` = outflow for the month as the budget month page defines it (the plan verifies the sign convention against `/budget/month` and pins it in a test), `budgeted`, `pct = clamp(round(spent / budgeted × 100), 0, 100)` (0 when budgeted is 0), `over = spent > budgeted && budgeted > 0` (bar turns red).
- **Card:** "Gastado **$8,240** de $12,000" / "Spent … of …", the bar, and "🧾 {n} tickets por revisar" → `/budget/receipt-drafts` when `n > 0`. The card itself links to `/budget/month`. **No scan button.**

## Backend

### `KidSummary` additions (`backend/app/schemas/oversight.py`, `OversightService.get_summary`)

| Field | Type | Definition |
|-------|------|------------|
| `required_total_today` | `int` | Non-bonus assignments for the kid dated family-local today — **the same set `get_daily_progress` counts as `required_total`** for that kid and date. |
| `required_done_today` | `int` | Of those, `status == COMPLETED` — same as `required_completed`. (Cancelled rows count in the total and never as done, exactly like the kid's own "N/M hoy".) |
| `required_open_today` | `int` | Of those, status PENDING or OVERDUE — the "still to do today" count the nudge uses. |
| `overdue_count` | `int` | Non-bonus assignments dated **before** today with status PENDING or OVERDUE — the same set `list_open_mandatory_before` returns. |
| `last_nudged_at` | `Optional[datetime]` | Latest `created_at` of a `parent_nudge` notification to the kid, or null. |

- Each is **one grouped query** for the whole family (the summary stays "fixed queries, no N+1").
- Existing fields and their meanings are unchanged (`open_today` stays).
- **Invariant test:** for every kid in a seeded family (assignments across pending / completed / awaiting approval / cancelled / overdue / bonus), `required_total_today` and `required_done_today` equal `get_daily_progress(kid)["required_total"/"required_completed"]`, `required_open_today` equals the count of that day's required assignments with status PENDING/OVERDUE, and `overdue_count == len(list_open_mandatory_before(kid, today))`.

### Nudge — `POST /api/oversight/nudge/{kid_id}`

- **Auth:** `require_parent_role`. Service `OversightService.nudge(db, family_id, parent, kid_id, now)`.
- **Target:** a user with `id == kid_id`, same `family_id`, role TEEN or CHILD, `is_active`. Anything else → **404** (no existence oracle across families).
- **Something to do:** `open = required_open_today + overdue_count` (same definitions as above). `open == 0` → **409** `{"detail": "nothing_to_nudge"}`.
- **Cooldown:** a `parent_nudge` notification to this kid with `created_at > now − 3 h` (from **any** parent) → **429** `{"detail": "nudge_cooldown", "retry_after_seconds": <int>}` plus a `Retry-After` header.
- **Send:** new `NotificationType.PARENT_NUDGE = "parent_nudge"` via the existing `NotificationService.create_localized` path (inbox + push, respects the 10-per-hour push cap), `user_id = kid_id`, link `/dashboard`.
  - Copy key `parent_nudge`: title "⏰ Te faltan {n} tareas" / "⏰ {n} chores to go" (singular: "⏰ Te falta 1 tarea" / "⏰ 1 chore to go"); body "{parent} te lo recuerda · tócalo para verlas" / "{parent} is reminding you · tap to see them". `{parent}` = the parent's first name.
- `PARENT_NUDGE` joins `SUPERSEDING_TYPES`, so a new nudge marks the kid's older unread nudge read (no pile-up; the kid's badge counts one).
- **Response 200:** `{"sent": true, "open": <n>, "nudged_at": <iso>}`.
- **Constant:** `NUDGE_COOLDOWN = timedelta(hours=3)` in `oversight_service.py`. The frontend mirrors it as `NUDGE_COOLDOWN_MS = 3 * 3600 * 1000` in `parentHub.ts` (display only — the server is the authority); a test on each side pins the value to 3 h.
- No migration: the notification type is a string on a `String(48)` column.

## Units and files

| File | Responsibility |
|------|----------------|
| `backend/app/schemas/oversight.py` | 5 new `KidSummary` fields; `NudgeResponse` |
| `backend/app/services/oversight_service.py` | grouped queries for the new fields; `nudge()`; `NUDGE_COOLDOWN` |
| `backend/app/api/routes/oversight.py` | `POST /nudge/{kid_id}` |
| `backend/app/models/notification.py` | `PARENT_NUDGE` |
| `backend/app/services/notification_service.py` | `parent_nudge` copy (es/en, singular/plural); `SUPERSEDING_TYPES` += `PARENT_NUDGE` |
| `frontend/src/pages/api/oversight/[...path].ts` (new) | same-origin proxy for `/api/oversight/*` (none exists today; SSR calls the backend directly, but the browser's nudge POST needs it). Follows the existing `[...path].ts` proxies (`url.pathname`, no trailing-slash redirect). |
| `frontend/src/lib/reviewQueue.ts` (new) | `buildReviewQueue` — pure, vitest |
| `frontend/src/lib/approvalActions.ts` (new) | `submitDecision` — request shapes, vitest with a fetch stub |
| `frontend/src/lib/parentHub.ts` (new) | `kidRowView`, `budgetGlanceView`, `NUDGE_COOLDOWN_MS` — pure, vitest |
| `frontend/src/components/home/ReviewCard.astro` (new) | one review card + expand/confirm UI |
| `frontend/src/components/home/KidRow.astro` (new) | one kid row + nudge button |
| `frontend/src/components/home/SetupCard.astro` (new) | setup checklist card |
| `frontend/src/components/home/ParentHub.astro` (new) | section layout + the page's client script (review queue, nudge, dismiss) |
| `frontend/src/pages/parent/index.astro` | fetches; renders header slot + `ParentHub`; removes tiles, old kid cards, payday banner, top boss bar, top push button, onboarding widget, `GigsIntroBanner` |
| `frontend/src/pages/parent/approvals.astro` | `decide()` delegates to `submitDecision` |
| `frontend/src/components/GigsIntroBanner.astro` | deleted |

## Error handling

- Every SSR fetch is fail-open (`apiFetch` never throws): no summary → no *Hoy* section; no paycheck for a kid → plain done/total bar; any pending list failing → that list counts as empty; no month → no budget card; no family cup → no mini card.
- Review: a card leaves only on 2xx; failures keep it with a toast carrying the backend reason.
- Nudge: 409/429 map to their states above; network errors toast and re-enable.
- Setup dismiss failure: card stays, toast.

## Testing

- **pytest**
  - `backend/tests/test_oversight_today_fields.py`: the invariant above (parity with `get_daily_progress` / `list_open_mandatory_before`) across all statuses incl. cancelled and bonus; other families never counted; `last_nudged_at` null, then the latest of two nudges.
  - `backend/tests/test_parent_nudge.py`: 200 creates one `parent_nudge` notification for the kid with the right copy + link and calls the push path; singular/plural copy; second nudge within 3 h → 429 with `retry_after_seconds` in (0, 10800]; **other parent** within 3 h → 429 too; after 3 h (frozen `now`) → 200 and the older unread nudge is marked read (supersede); kid with nothing open → 409; kid in another family → 404; parent as target → 404; inactive kid → 404; child/teen caller → 403.
- **vitest** (every test mutation-checked)
  - `frontend/test/review-queue.test.ts`: merge of 3 kinds, oldest-first, missing timestamps last and stable, `allowPartial` false for collaboration and non-task kinds.
  - `frontend/test/approval-actions.test.ts`: exact URL + body per kind and grade; non-2xx surfaces `detail` then `message`; network error → `{ok:false}`.
  - `frontend/test/parent-hub.test.ts`: `kidRowView` nudge states (ready / cooldown at 2 h 59 m / ready again at 3 h 01 m / done / none), overdue chip, meter only for chore mode; `budgetGlanceView` pct clamp, zero budget, over-budget flag, drafts line.
- `astro check` + `astro build`.
- **Manual on prod (demo family only, verify `family_id == b8312b5a…` first — the demo family shares the real family's name):** demo parent home renders all sections; one ✓ approval of a demo item; one nudge to `diego.demo` (then the button shows cooldown); setup card absent (demo onboarding done); `/parent/approvals` still approves.

## Rollout

One PR → CI → merge → `deploy-onprem.sh` (no migration) → the manual checks above. The **only prod writes**: one review decision on a demo item and one nudge to the demo teen, both in the demo family. Never in the owner's real family (`1998e48d-2ef0-48b6-a437-cbb730ae935c`).
