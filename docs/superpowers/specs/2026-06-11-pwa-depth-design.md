# PWA Depth Design

## Goal

Three complementary PWA upgrades: offline shell caching (SW upgrade), install-to-home-screen banner, and bidirectional push notifications (children notified on task approval and reward redemption).

---

## 1. Offline Shell

### Service Worker upgrade (`frontend/public/sw.js`)

In-place upgrade, no new dependencies. Add cache version constant and three fetch strategies.

**Cache name:** `ftm-shell-v1`. Bump to `v2`, `v3`… on future breaking changes — the `activate` handler deletes all caches not matching the current name.

**Precache on `install`** (static assets unlikely to change):
```
/icon-192.png, /icon-512.png, /icon-maskable-192.png, /icon-maskable-512.png,
/favicon.svg, /manifest.webmanifest, /offline.html
```

**Fetch strategies:**

| Request type | Strategy | Rule |
|---|---|---|
| `/_astro/*` | Cache-first + populate on miss | Astro fingerprints these; safe to cache forever |
| `/api/*` | Network-only (no intercept) | Auth-sensitive, never stale |
| `navigate` mode | Network-first → `/offline.html` fallback | Shows branded offline page if network fails |
| Everything else | No intercept (passthrough) | Icons already precached; unknown resources stay network |

**`activate`**: delete all caches where name ≠ `ftm-shell-v1`, then `clients.claim()`.

**Cross-origin requests**: always passthrough (skip event handling).

### Offline page (`frontend/public/offline.html`)

Simple branded standalone HTML page. No external resources (fully self-contained so it works when cache is the only source):
- Brand color background (`#4FB8E6`)
- Icon (inline SVG or base64 embedded)
- Bilingual message: "Sin conexión — Reconnect to continue / Sin conexión — Reconéctate para continuar"
- Retry button: `window.location.reload()`

---

## 2. Install Banner

### Where

Global `<script>` block in `frontend/src/layouts/Layout.astro` (runs on every page, every role).

### Chrome/Edge/Android flow

1. Listen for `beforeinstallprompt` → `preventDefault()` → store as `deferredPrompt`
2. After 3 seconds, if not already installed (`navigator.standalone !== true`) and not recently dismissed, inject banner into DOM
3. Clicking **Add / Agregar**: call `deferredPrompt.prompt()` → `await deferredPrompt.userChoice` → hide banner
4. Clicking **×**: dismiss, set localStorage `ftm-install-dismissed` = `Date.now()`, hide banner
5. Auto-hide after 15 seconds if user ignores

### iOS/Safari flow

`beforeinstallprompt` never fires on iOS. Detect via:
```javascript
const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
const isStandalone = navigator.standalone === true;
```
If iOS + not standalone + not dismissed: show static tip after 3 seconds.

### Dismiss persistence

localStorage key `ftm-install-dismissed` stores Unix timestamp. Re-show after 30 days (`Date.now() - stored > 30 * 86400 * 1000`).

### Banner HTML (injected dynamically)

```
┌──────────────────────────────────────────────────────┐
│ 📱  Agrega a tu pantalla / Add to home screen  [Add] [×] │
└──────────────────────────────────────────────────────┘
```

Fixed bottom, `z-50`, brand-coral/10 background with border, rounded-t-2xl. Bilingual: detect `document.cookie` for `lang=es` pattern.

iOS tip variant shows Share icon (↑) and text "Toca Compartir → 'Añadir a inicio' / Tap Share → 'Add to Home Screen'". No button — informational only.

### Skip conditions

- `navigator.standalone === true` (already installed)
- `window.matchMedia('(display-mode: standalone)').matches` (same, cross-browser)
- `ftm-install-dismissed` set within last 30 days

---

## 3. Child Push Notifications

### New backend call sites

Both are fire-and-forget (try/except, warning log, never block main flow).

**Task/gig approved → notify claimer**

File: `backend/app/services/task_assignment_service.py`, inside `approve_gig`.  
After the existing `await db.commit()` that credits points (where the onboarding hook was added in the previous feature), add:

```python
try:
    from app.services.push_service import PushService
    await PushService.send_to_user(db, assignment.user_id, {
        "title": "¡Tarea aprobada! 🎉" if lang == "es" else "Task approved! 🎉",
        "body": f"{task_title} — {points} pts",
        "url": "/dashboard",
        "tag": "task-approved",
    })
except Exception:
    import logging
    logging.getLogger(__name__).warning("push task-approved failed", exc_info=True)
```

Note: language is not available in the service layer — use a fixed bilingual title (`"¡Tarea aprobada! / Task approved! 🎉"`). The child's device language will render it correctly regardless.

**Reward redeemed → notify redeemer**

File: `backend/app/services/reward_service.py`, inside `redeem_reward`.  
After the `await db.commit()` that persists the redemption:

```python
try:
    from app.services.push_service import PushService
    await PushService.send_to_user(db, user_id, {
        "title": "¡Recompensa canjeada! 🎁",
        "body": reward.title,
        "url": "/rewards",
        "tag": "reward-redeemed",
    })
except Exception:
    import logging
    logging.getLogger(__name__).warning("push reward-redeemed failed", exc_info=True)
```

### Push subscription for children

`EnablePushButton` component currently absent from the child/teen main page.

Add `EnablePushButton` to `frontend/src/pages/dashboard.astro` inside the `isKid` section (near the top of the page body), so children are prompted to subscribe when they use their dashboard.

Import pattern (already used on other pages):
```astro
import EnablePushButton from "@/components/EnablePushButton.astro";
```

Place below the greeting/points header, above the task list.

---

## Migration

No DB schema changes. No new models. No Alembic migration needed.

---

## Testing

**SW / offline:**
- Chrome DevTools → Application → Service Workers: verify `ftm-shell-v1` installed
- Network tab → throttle to Offline → navigate to any page → `/offline.html` renders
- Navigate to `/_astro/*` asset offline → served from cache

**Install banner:**
- Chrome DevTools → Application → Manifest → "Add to homescreen" button → banner appears
- Click ×, reload → banner suppressed
- Set `ftm-install-dismissed` to 31-days-ago in localStorage → banner reappears

**Child push:**
- `test_push_task_approved` — mock `PushService.send_to_user`, call `approve_gig`, assert called with child user_id and `tag="task-approved"`
- `test_push_reward_redeemed` — mock `PushService.send_to_user`, call `redeem_reward`, assert called with `tag="reward-redeemed"`

---

## Out of Scope

- Push for gig claim submissions (already exists via `fan_out_pending_gig`)
- Background sync / offline form submissions
- Push notification preferences UI (per-type opt-out)
- Web Share API
- Periodic background sync
