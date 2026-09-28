# UX-A — Prod Hygiene Pack — Design

**Date:** 2026-09-27
**Status:** approved in chat (2026-09-27), pending written-spec review
**Program:** UX/GUI/engagement program, sub-project **A** of A → C → B → D → E
**Evidence:** `docs/audit/2026-09-27-ux-competitive/findings.md` (F1, F3–F7)

## Goal

Remove the things in production that look broken, leak internals, or bury
signal in noise — before any redesign work (sub-project C) builds on top of
them. Every item here is a fix to an existing flow; no new product surface.

Success = after deploy, on prod:

1. Parent Settings shows push as configured (it is), with a device count.
2. The stale Apple subscription that 403s on every send is pruned (or its
   reason is logged, if it is not a key mismatch).
3. Demo users' unread badge drops from ~75–214 to a handful.
4. Jarvis history shows no `[actions: …]` text; money reads `$13,849 MXN`.
5. `/kiosk` without / with a bad token shows a friendly page, not raw text.
6. Routines are reachable from the kid and parent More sheets and the kid
   dashboard.
7. No CSP console error; Cloudflare Web Analytics beacon loads.

## Non-goals

- Kid / parent / teen home redesign, contextual push prompts → sub-project C.
- Dark mode, native `alert/confirm/prompt`, visual-system cleanup → B.
- Levels, badges, app-icon badging → D.
- Any change to what the model sees in Jarvis history.

## Verified facts this design relies on (prod .91, 2026-09-27, read-only)

- VAPID public key is 87 chars; private key is the 43-char raw base64url form
  (not PEM); the private key derives exactly the configured public key.
- `push_subscriptions`: 3 rows total (2 `web.push.apple.com`, 1 FCM).
  Logs, 7 days: 3× `403 Forbidden`, all the same Apple endpoint (created
  2026-07-16). Only 404/410 prune today, so it retries forever.
- `notifications`: 958 unread across 10 users (avg 87, max 214);
  `task_due` 454 + `task_assigned` 210 unread. Type is stored as the
  lowercase enum value (`'task_due'`).
- Both `task_assigned` copy keys (`task_assigned`, `task_assigned_one`) are
  emitted only by the weekly-shuffle aggregate fan-out
  (`task_assignment_service.py` ~L1218), so a newer one fully replaces an
  older one.
- `send_morning_reminders` dedups on "a `TASK_DUE` row exists since local
  midnight" — it does not look at read state, so marking old rows read does
  not re-trigger reminders.
- Jarvis stores `reply + "\n\n[actions: …]"` in `JarvisMessage.content`
  (`jarvis_service.py` ~L790 and ~L1028). `_load_history` feeds that content
  back to the model, so the suffix is intentional context. The live SSE /
  JSON reply already excludes it; only `GET /api/jarvis/history` leaks it.

## Design

### 1. Push correctness (F1)

**`backend/app/services/push_service.py`**

- New `PushService.keypair_status() -> dict` returning
  `{"configured": bool, "valid_keys": bool, "error": str | None}`.
  `configured` = both keys non-empty. `valid_keys` = the private key loads via
  `py_vapid.Vapid.from_string()` (raw or DER, base64url — exactly what
  pywebpush uses for a real send; a PEM string would fail there too) **and** its
  derived public key (X9.62 uncompressed point, base64url, no padding)
  equals `VAPID_PUBLIC_KEY` with any `=` padding stripped. Any exception →
  `valid_keys=False`, `error` = exception class name (never key material).
- `send_to_user`: on `WebPushException`, read `status` and a `reason`:
  JSON `reason` field if the body parses (Apple), else the first 200 chars of
  the body text (FCM). Always include `reason` in the warning log.
  Prune the endpoint when:
  - `status in (404, 410)` (unchanged), or
  - `status == 403` and the reason says the subscription belongs to another
    key: Apple `VapidPkHashMismatch`, or FCM text containing
    `does not correspond`.
  Any other 403 (e.g. `BadJwtToken`) is our bug, not the subscription's —
  log only, never prune.

**`backend/app/api/routes/push.py`** — `/health` uses `keypair_status()`
instead of the length heuristic. Response keeps its current keys
(`configured`, `valid_keys`, `claim_email`, `subscription_count`,
`public_key_length`, `private_key_length`) so the settings page needs no
change to go green.

**`frontend/src/components/EnablePushButton.astro`** — on load, decide what
to show, in this order:

1. `PushManager` missing **and** iOS (iPhone/iPad UA) **and** not standalone →
   hide the button, show a one-line hint: "Para recibir avisos, instala la app:
   Compartir → Agregar a inicio" / EN equivalent.
2. `PushManager` missing otherwise → hide the whole component.
3. `Notification.permission === "denied"` → hide button, show "Avisos
   bloqueados en el navegador" / EN.
4. `GET /api/push/public-key` returns non-2xx → hide the whole component.
5. Existing subscription made with the **current** server key → hide the
   whole component, and re-post it to `/api/push/subscribe` at most once a
   day (a row the server pruned comes back). Made with an **older** key →
   unsubscribe it and fall through to 6 (every send to it would 403).
6. Otherwise → current button, current subscribe flow.

### 2. Notification noise (F7)

**`backend/app/services/notification_service.py`**

- `SUPERSEDING_TYPES = {NT.TASK_DUE, NT.TASK_ASSIGNED}`.
- In both `create()` and `create_no_commit()`: when `user_id` is not None and
  `type` is in `SUPERSEDING_TYPES`, first execute
  `UPDATE notifications SET is_read = true, read_at = now()
   WHERE family_id = :f AND user_id = :u AND type = :t AND is_read = false`
  in the same session/transaction, then insert the new row. (All
  `create_localized*` paths funnel through these two.)
- `UNREAD_BADGE_WINDOW_DAYS = 14`. `unread_count()` additionally requires
  `created_at >= now() - 14 days`. `list_for_user()` is unchanged (old items
  stay visible, they just stop inflating the badge).

**Alembic data migration** `mark_stale_reminders_read` (new head):
upgrade runs
`UPDATE notifications SET is_read = true, read_at = now()
 WHERE is_read = false AND type IN ('task_due', 'task_assigned')
 AND created_at < now() - interval '2 days'`.
Downgrade is a documented no-op (read state is not restorable and nothing
depends on it). No schema change.

**`frontend/src/pages/notifications.astro`**

- Group items under "Hoy / Ayer / Antes" (EN "Today / Yesterday / Earlier"),
  computed in the family timezone. Grouping is a pure helper in
  `frontend/src/lib/` so vitest can cover it.
- Each card is one tap target: tapping marks it read (existing
  `POST /api/notifications/{id}/read` proxy) and then navigates to `link`
  if present; with no link it just marks read in place. Remove the separate
  "View →" and "Mark read" links. Unread = a coral dot + bolder title.
- "Mark all read" stays.

### 3. Jarvis display (F3)

**Backend**

- `jarvis_service.split_actions_suffix(content) -> tuple[str, list[str]]`:
  strips a trailing `\n\n[actions: a, b]` and returns the clean text plus
  `["a", "b"]`; content without the suffix returns `(content, [])`.
- `GET /api/jarvis/history`: `HistoryItem` gains `actions: list[str] = []`;
  the route applies `split_actions_suffix` to assistant rows. Storage and
  `_load_history` are untouched.
- `SYSTEM_BASE` and `SYSTEM_TEEN` gain one rule: write money with the currency
  symbol and thousands separators (e.g. `$13,849 MXN`), never raw integers or
  cents.

**Frontend**

- `frontend/src/lib/jarvis-chat.ts`: `formatActionLabel(raw)` —
  `"budget_spending_report(ok)"` → `"budget spending report ✓"`,
  `"(pending)"` → `⏳`, any other status → `⚠`.
- `parent/jarvis.astro`: history bubbles render `m.actions` as the same chips
  live replies already render; live chips switch to `formatActionLabel` too.
  `soporte.astro` renders chips only if `actions` is non-empty.

### 4. Kiosk without a valid token (F4)

**`frontend/src/pages/kiosk.astro`** — replace both
`return new Response("Missing token", 400)` and
`return new Response("Invalid token", …)` with a branded standalone HTML
page (rendered by a pure helper in `frontend/src/lib/kiosk-unpaired.ts`,
because the page bails out before its own template). Three reasons:
missing token → 400; invalid/revoked token (4xx from the snapshot API) → that
status; backend unreachable or 5xx → 503 with "Tablero no disponible /
Reintentar" (a wall tablet mid-deploy must not be told its link expired).

- Title: "Esta pantalla no está vinculada" / "This screen isn't paired".
- Subtitle: missing → "Abre el enlace de kiosko desde Ajustes → Kiosko";
  invalid → "El enlace expiró o fue revocado".
- Button: if an `access_token` cookie is present → "Vincular esta pantalla"
  → `/parent/kiosk`; else → "Iniciar sesión" → `/login`.
- ES/EN by `lang` cookie, like the rest of the page.

### 5. Routines discoverability (F5)

- `frontend/src/components/MoreSheet.astro`: kid links get
  `{ href: "/routines", label: "Rutinas" / "Routines" }` right after Inbox;
  parent links get `{ href: "/parent/routines", … }` right after Tasks.
  New inline SVG icon (sun-over-list), same stroke style as the others.
  Not tied to the module registry (routines are core, like tasks).
- `frontend/src/pages/dashboard.astro`: SSR-fetch `GET /api/routines/today`
  (fail-open: any error → no strip). If it returns ≥1 routine with steps,
  render a compact strip inside the kid header, right under the greeting and
  above the points card: one
  row per routine (max 2, morning/evening first) — icon, localized name,
  `steps_done/total_steps`, ✓ when `completed`, whole row links to
  `/routines`. No routines → nothing rendered.

### 6. CSP + privacy notice (F6)

- `frontend/src/middleware.ts`: `script-src` adds
  `https://static.cloudflareinsights.com`; `connect-src` adds
  `https://cloudflareinsights.com`. Update the comment block above the
  directives to say why.
- `frontend/src/pages/privacidad.astro` (ES + EN blocks): the Cloudflare
  processor line adds "y medición anónima y agregada de visitas y rendimiento
  (Cloudflare Web Analytics, sin cookies)" / EN equivalent. The cookies
  section's "no third-party analytics cookies" statement stays true and is
  unchanged.

## Error handling

- Push: `keypair_status()` never raises; `send_to_user` stays best-effort and
  only widens pruning for the two explicit mismatch reasons.
- Supersede `UPDATE` runs inside the caller's transaction: if the insert
  fails, the update rolls back with it (no "all reminders vanished" state).
- Dashboard routines fetch is fail-open; `/notifications` falls back to plain
  navigation if the mark-read call fails.
- Kiosk friendly page makes no API call beyond the existing snapshot fetch.

## Testing

Backend (pytest, TDD, run targeted files — never the full suite from a
subagent):

- `test_push_subscriptions.py`: `keypair_status` for raw-key pair, PEM pair,
  mismatched pair, garbage key, empty keys; `send_to_user` prunes on 404/410,
  on 403 `VapidPkHashMismatch`, on FCM "does not correspond"; does **not**
  prune on 403 `BadJwtToken`; logs the reason. `webpush` mocked.
- `test_notifications.py`: creating `task_due` marks the same user's older
  unread `task_due` read; does not touch other types, other users, other
  families, or family-wide rows; same for `task_assigned`; `create_no_commit`
  path too; `unread_count` ignores unread rows older than 14 days;
  `send_morning_reminders` stays idempotent.
- Migration: CI's upgrade → downgrade −1 → upgrade round-trip.
- `test_jarvis_*`: `split_actions_suffix` cases (none, one, many, suffix-like
  text mid-message untouched); history endpoint returns clean `content` +
  `actions`; model history (`_load_history`) still contains the suffix.

Frontend: vitest for `formatActionLabel` and the notification day-grouping
helper; `astro check` + `astro build`; manual Playwright pass on local
(notifications tap-through, kiosk no-token page, More sheet links,
dashboard strip with/without routines, push button states where emulable).

Every new test is mutation-checked (break the code, see it fail).

## Rollout

One PR from `feat/ux-a-prod-hygiene` → CI green → merge → `deploy-onprem.sh`
(runs the data migration) → verify the seven success criteria on prod
(read-only checks as the demo family + `podman logs` for the push reason). If
the stale Apple endpoint's logged reason is not a key mismatch, record it in
the worklog and decide in a follow-up — do not widen pruning blindly.
