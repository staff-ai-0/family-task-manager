# UX-D4a — Pings: App-Icon Number + Smart Reminders — Design

**Date:** 2026-10-01
**Status:** design approved in conversation 2026-10-01; awaiting written-spec review
**Program:** UX/GUI program, sub-project **D4a** of D (progression & engagement loop). D1 streak + rank (PRs #287, #289, #292), D2 badges (PR #290) and D3 weekly quest (PR #291) shipped. D4 was split by the user on 2026-10-01: **D4a pings** (this spec) → Jarvis check-in for teens → **D4b** mystery reward.
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` (row D: the loops that bring kids back are the ones that reach them outside the app; a streak nobody is reminded of is lost silently).
**Builds on:** `docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md`, `docs/superpowers/specs/2026-10-01-ux-d3-weekly-quest-design.md`.

## Goal

D1–D3 gave kids a streak, a rank, badges and a weekly quest, but every one of them is only visible after the kid opens the app. D4a adds the two cheapest ways to reach a family member who has not opened it:

1. **A number on the app icon** — "things waiting for you", by role.
2. **Two smart pushes for kids** — sent in the evening, only when a specific thing is about to be lost or is one step away.

It must stay quiet. The existing morning reminder already tells kids what they have today; D4a adds at most one more push per kid per day, and none when there is nothing the kid can do about it.

**Decisions (user, 2026-10-01):**
- Two smart pushes only: **streak at risk** and **weekly quest one step away**. At most one per kid per day. Nothing when the kid has nothing left to do.
- The icon number means "things waiting for you": kids/teens = chores still open; parents = items waiting for review.
- **On by default**, with one family switch in parent settings. Not opt-in: there is no effect on the family's economy, and a device only receives pushes after someone allowed notifications on it.
- The evening check runs at **6:00 pm** family-local time, the same for every family.
- Build: one hourly server sweep for the pushes; a count the app asks for after each page load and that every push carries.

**Not in D4a:** a per-kid switch, a configurable time, quiet hours, smart pushes for parents, any push about badges or rank, the mystery reward (D4b), the Jarvis teen check-in (its own sub-project), changes to the morning reminder, native-app (iOS/Android) badge code, pet effects.

## Rules

### Who

Smart pushes go to kids and teens only (roles CHILD, TEEN — `KID_ROLES`) who are participating members (active and parent-approved — `TaskAssignmentService._participating_member_clause`) and have at least one row in `push_subscriptions`. A kid with no subscribed device gets nothing at all — no push and no inbox entry (an "ends tonight" line first seen the next morning would be false).

The icon number is for every role.

### When

The sweep job runs hourly at minute 0. It acts on a family while that family's local time (`families.timezone`, UTC on an invalid name) is **18:00–20:59**. The window exists for recovery only: with the server up, every eligible kid is handled by the 18:00 run and the later runs find nothing to do. If the server was down at 18:00, the 19:00 or 20:00 run sends instead. After 20:59 nothing is sent that day.

### Push 1 — streak at risk

Sent when all of these hold at sweep time:

- the kid's streak (`compute_streak(...).days`, today not yet counted) is **≥ 3**;
- the kid has **at least one open chore today**: a non-bonus assignment dated today with status `PENDING` or `OVERDUE`;
- today is **not already lost**: none of today's non-bonus, non-cancelled assignments is graded `missed` or rejected (if one is, finishing the rest cannot save the day, so the push would be false).

Wording depends on whether this week's free pass is already spent (`StreakResult.shield_used`):

| Free pass | Title ES / EN |
|---|---|
| already used | "🔥 Tu racha de {days} días termina esta noche" / "🔥 Your {days}-day streak ends tonight" |
| unused | "🔥 Conserva tu racha de {days} días" / "🔥 Keep your {days}-day streak" |

Bodies, four copy keys (singular and plural are separate keys — the existing `_one` convention in `notification_service.py`); `{n}` is the number of open chores today:

| Key | Body ES | Body EN |
|---|---|---|
| `streak_at_risk_last_one` (pass used, n = 1) | "Te falta 1 tarea hoy. Termínala para conservarla." | "1 chore left today. Finish it to keep it." |
| `streak_at_risk_last` (pass used, n > 1) | "Te faltan {n} tareas hoy. Termínalas para conservarla." | "{n} chores left today. Finish them to keep it." |
| `streak_at_risk_pass_one` (pass unused, n = 1) | "Te falta 1 tarea hoy. Termínala y guarda tu pase libre 🛡️." | "1 chore left today. Finish it and save your free pass 🛡️." |
| `streak_at_risk_pass` (pass unused, n > 1) | "Te faltan {n} tareas hoy. Termínalas y guarda tu pase libre 🛡️." | "{n} chores left today. Finish them and save your free pass 🛡️." |

Both wordings are true: with the pass unused, missing today spends the pass and keeps the streak; with it used, missing today resets the streak. "Today" everywhere in the sweep is the family-local date of the sweep's `now`.

### Push 2 — quest one step away

Sent when all of these hold at sweep time:

- the family has quests on (`families.quest_bonus_points > 0`);
- the kid has a `weekly_quests` row for this week that is not rewarded, and progress is exactly `target − 1` (progress derived by `QuestService.stats_for`, the same strict rule the quest card uses);
- the missing step **can still be done today**:

  | Quest | Can be done today when |
  |---|---|
  | `on_time` | a non-bonus assignment dated today is still `PENDING` (the quest's own rule: an `OVERDUE` chore can no longer count as on time) |
  | `perfect_days` | the same, and no non-bonus assignment dated today has already failed for the quest (`chore_state` = "no") |
  | `extra_mile` | a bonus assignment dated today is still open (`PENDING` or `CLAIMED`) |
  | `go_getter` | `QuestService._open_gigs` reports at least one gig open to the kid (0 when the gigs module is off or the kid is in star mode) |

  These reuse `chore_state` / `bonus_state` from `quest_service.py`, so the nudge can never promise a step the quest would not count. The quest's own bonus must be above 0 (the copy names it).

- no `quest_nudge` notification exists for the kid since Monday 00:00 family-local (once per quest).

The sweep never creates a quest and never pays one: a kid who has not opened the app this week has no quest row and gets no nudge.

Copy (one key): "🏁 Te falta 1 para tu misión de la semana" / "🏁 1 away from this week's quest"; body "Complétala y gana +{bonus} puntos." / "Finish it for +{bonus} points." `{bonus}` is `weekly_quests.bonus_points`. The copy is generic on purpose — quest names live only in the frontend (`lib/quest.ts`).

### Shared rules

- **One per day:** a kid who already has a `streak_at_risk` or `quest_nudge` notification created since today's family-local midnight is skipped.
- **Priority:** when both pushes apply, the streak push is sent. The quest nudge stays eligible and is considered again the next day.
- **Language:** the kid's own (`create_localized` resolves `preferred_lang`).
- **Link:** both open `/dashboard`.
- **Rate limit:** unchanged. `NotificationService.create` already skips the push (keeping the inbox entry) when the user received more than 10 notifications in the last hour. A smart push skipped this way is not retried that day.
- **Family switch off:** the family is skipped entirely.

## Backend

### Notification types and the send record

Two new values in `NotificationType`: `STREAK_AT_RISK = "streak_at_risk"`, `QUEST_NUDGE = "quest_nudge"` (`notifications.type` is a plain string column — no migration). Both join `SUPERSEDING_TYPES`, so a new one marks the kid's older unread one of the same type as read.

These rows are the **only** record that a smart push was sent — the pattern `send_morning_reminders` already uses (its idempotency key is a `TASK_DUE` row since local midnight). No new table and no new column on `weekly_quests`. This is safe because notification rows are never deleted: the API can only mark them read, and superseding marks read too.

Expiry, so nothing stale stays in the inbox: `streak_at_risk` expires at the next family-local midnight; `quest_nudge` expires at the end of the quest week (next Monday 00:00 family-local). `list_for_user` and `unread_count` already hide expired rows; the idempotency queries read by `created_at` and ignore expiry.

### `backend/app/services/ping_service.py` (new)

Pure functions (no DB, unit-tested directly):

- `in_ping_window(local_now: datetime) -> bool` — hour in 18..20 (`PING_FIRST_HOUR = 18`, `PING_LAST_HOUR = 20`).
- `streak_ping(days: int, shield_used: bool, open_today: int, day_lost: bool) -> str | None` — returns the copy key (`streak_at_risk_last`, `streak_at_risk_last_one`, `streak_at_risk_pass`, `streak_at_risk_pass_one`) or `None`. `STREAK_PING_MIN_DAYS = 3`.
- `quest_ping(progress: int, target: int, rewarded: bool, can_do_today: bool, nudged_this_week: bool) -> bool`.
- `pick_ping(streak_key: str | None, quest_ok: bool) -> str | None` — streak first, else `"quest_nudge"`, else `None`.

`PingService`:

- `waiting_count(db, user) -> int` — the icon number (below).
- `waiting_count_for_id(db, user_id) -> int` — loads the user, then the same; used by the push path.
- `run_evening_sweep(db, now: datetime | None = None) -> int` — returns the number of pings created. `now` is injectable (tests never depend on the wall clock). Steps:
  1. Select non-deleted families with `smart_reminders_enabled` true; keep those whose local time is in the window.
  2. Per family: select participating kids/teens that have a push subscription and no smart-ping row since local midnight.
  3. Per kid, inside its own `try/except` (one kid failing is logged and never stops the rest): read today's non-bonus assignments (open count, day lost), compute the streak with the existing `ProgressService.day_states` + `compute_streak`, read the quest state read-only, decide with the pure functions, and create the notification with `NotificationService.create_localized(..., expires_at=..., push=True)`.
  4. Log one line: families in window, kids checked, pings sent.

### Scheduler

`main.py`: `_smart_ping_sweep` in the same shape as `_family_bank_payday_sweep` (own session, exceptions logged), registered `cron, minute=0, id="smart_ping_sweep"`. It runs on the scheduler leader only, like every other sweep.

### The icon number

`GET /api/notifications/waiting-count` → `{"count": int}`. Any authenticated role; scoped to the caller's `family_id`.

- **Kid / teen:** the open mandatory chores the kid home already shows — today's non-bonus assignments with status `PENDING` or `OVERDUE`, plus the carried-over ones from earlier days (`TaskAssignmentService.list_open_mandatory_before(today)`, the "Atrasadas" list). Bonus tasks are optional and never counted.
  - *Changed from the conversation, where older overdue chores were going to be cut off at the current week:* the number must equal what the screen shows. The home lists every carried-over chore, so a number that left some out would disagree with the app the moment the kid opens it.
- **Parent:** items awaiting review — task approvals (`TaskAssignmentService.list_pending_approvals`) + gig claims (`GigClaimService.get_pending_approvals`) + reward requests (`RewardService.list_pending_redemptions`). The same three lists `/parent/approvals` renders — with no module filter, exactly like that page — so the number equals its length.

The count is an `int` built from row counts (never a SQL `SUM`), so it serializes as a JSON number.

### Every push carries the count

`PushService.send_to_user` adds `badge: <waiting_count_for_id(user_id)>` to the payload when the caller did not set one. One place, so every existing and future push updates the icon. If computing the count fails, the push is sent without the key (logged). The count is computed after the triggering change is committed, so a parent's "new gig to review" push already includes that gig.

`NotificationService.create` / `create_localized` gain an optional `push_tag: str | None` that is passed through as the payload `tag`; smart pings use `"ftm-smart"`, so a newer one replaces an older one still on the lock screen.

### Family switch

`families.smart_reminders_enabled` — `Boolean`, `NOT NULL`, default and server default `true`. One migration (`family_smart_reminders`, down-revision `weekly_quests`): add the column, nothing else. `FamilyUpdate.smart_reminders_enabled: Optional[bool]`; `FamilyResponse.smart_reminders_enabled: bool`. Parent-only update, through the existing family update route.

No new table, so the family export registry is unchanged.

## Frontend

### `frontend/src/lib/appBadge.ts` (new)

- `badgeAction(count: unknown) -> { op: "set"; n: number } | { op: "clear" }` — pure: a positive integer sets, anything else clears.
- `applyAppBadge(count)` — feature-detects `navigator.setAppBadge` / `clearAppBadge`; a browser without them does nothing; rejections are swallowed.
- `refreshAppBadge()` — `GET /api/notifications/waiting-count`, then `applyAppBadge`. A 401/403 clears the number (the session is gone); any other failure leaves the current number alone.

### Wiring

- `BottomNav.astro` (on every logged-in app page) fetches `waiting-count` during server render and puts it on the nav as `data-waiting-count`. Its script applies that number on page load — no extra request — and calls `refreshAppBadge()` on `visibilitychange` → visible (the app returning from the background), on the existing `ftm:deck-completed` / `ftm:deck-empty` events (a kid finished a chore), and on a new `ftm:waiting-changed` event.
- The parent "Approve" badge reads the same count instead of fetching the two approval lists (one request instead of two; it now includes reward requests, which the approvals page already lists).
- `lib/approvalActions.ts` dispatches `ftm:waiting-changed` after a successful approve / reject.
- `Layout.astro`: a page rendered without a session cookie clears the number — a shared phone never keeps the last user's count. Logout redirects to `/login`, which is such a page, so no separate logout handler is needed.

### Service worker

`public/sw.js` push handler: when `payload.badge` is a number, set or clear the app badge inside the same `event.waitUntil` as `showNotification` (feature-detected; a failure never blocks the notification). `tag` already comes from the payload. The worker already calls `skipWaiting()` + `clients.claim()`, so the new handler takes over on the next visit.

### Settings

`parent/settings/family.astro`, a new section `#smart-reminders-section` directly under `#quest-section`: one checkbox switch, "Recordatorios inteligentes para los hijos" / "Smart reminders for kids", with one line: "A las 6:00 pm avisamos a tus hijos solo si su racha está en riesgo o les falta un paso para su misión de la semana. Máximo un aviso al día." / "At 6:00 pm we tell your kids only when their streak is at risk or they are one step from their weekly quest. One reminder a day at most." Saves immediately through the family update route; `showToast` confirms or reports failure (and the switch reverts on failure). Kit classes only; no native dialogs.

## Platform limits (stated in the guide)

- The icon number needs the App Badging API: installed PWA on iPhone/iPad (iOS 16.4+, home screen, notifications allowed), Android and desktop Chrome/Edge. Elsewhere nothing is shown and nothing breaks.
- A kid whose device never allowed notifications gets no smart reminder.

## Error handling

- Sweep: per-kid `try/except`, logged; a failing family or kid never aborts the run. The job wrapper logs and swallows, like the other sweeps.
- Push failure: unchanged (swallowed by `NotificationService.create`; the inbox entry remains and counts as "sent today").
- Count endpoint failure in the browser: number left as is.
- Count failure in the push path: push sent without `badge`.

## Testing

Backend (`tests/test_ping_service.py`, `tests/test_waiting_count.py`, `tests/test_migration_family_smart_reminders.py`):

- Pure rules: window edges (17:59, 18:00, 20:59, 21:00); streak 2 vs 3; both wordings and both plural forms; no open chore → none; day already lost → none; quest at `target − 2`, `target − 1`, `target`; rewarded; already nudged; streak wins over quest.
- Sweep (with injected `now`): sends once and a second run in the same window sends nothing; outside the window sends nothing; a family in another timezone is evaluated by its own clock; switch off; kid without a subscription gets no notification row; parent never pinged; non-participating member skipped; quest nudged once per week, and again eligible the day after a streak push took priority; quest sweep creates no `weekly_quests` row and no point transaction; `expires_at` values; one kid raising does not stop the next; a second family's data never affects the first.
- Count: kid = today open + carried over, bonus excluded, completed excluded; parent = three queues; equals the lengths of the lists the screens use; other family's rows never counted; unauthenticated → 401.
- Push payload carries `badge`; a failing count still sends the push.
- Migration: column exists, existing families read `true`.
- No hard-coded calendar dates — all dates derive from the injected `now`.

Frontend (vitest, node — pure and source-structure tests):

- `badgeAction`: 0, negative, non-integer, `null`, string → clear; positive integer → set.
- Source checks: `BottomNav.astro` renders and applies `waiting-count` and listens for the refresh events; `Layout.astro` clears when logged out; `sw.js` handles `payload.badge`; `approvalActions.ts` announces a decision; the settings section exists with the switch.
- Existing guards stay green: `no-native-dialogs`, `visual-consistency`, `contrast`.

## Docs

- `docs/USER_GUIDE_EN.md` / `USER_GUIDE_ES.md`: new **17.5.5 Smart reminders and the app-icon number** (what the two reminders say and when, the one-a-day rule, the family switch, the platform limits) + table of contents.
- `CLAUDE.md`: a short paragraph (sweep and its window, notification rows as the send record, `waiting-count`, `badge` on every push).

## Rollout and production check

Deploy with `./scripts/deploy-onprem.sh`. No backfill. Every family, including existing ones, starts with the switch on.

Check in the demo family only (`b8312b5a-c9c0-469f-992f-8dbd412db4a7`, verified by id):

- the switch saves and persists across a reload;
- `waiting-count` for sofia equals the open chores on her home; for mariana it equals the review queue length, and the nav badge shows the same number.

The 6:00 pm push itself cannot be forced on production. It is covered by the sweep tests, and by reading the sweep's log line after the next 18:00 run.
