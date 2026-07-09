# Capacitor App-Store Wrap — Runbook

Wrapping **Family Task Manager** as native iOS + Android apps using
[Capacitor](https://capacitorjs.com/). This is the operator runbook for turning
the committed scaffold (`frontend/capacitor.config.ts`) into signed builds on the
App Store and Google Play.

> **Status: SCAFFOLD.** The only thing committed to this repo is
> `frontend/capacitor.config.ts` (an inert config the web build ignores) plus
> `.gitignore` rules for the generated native projects. **No `@capacitor/*`
> packages are in `package.json`** — adding them would drag native-only tooling
> into the CI `npm ci` web build. Everything below runs on an operator's Mac.
> Native builds cannot be produced headlessly; they need Xcode, the Android SDK,
> signing material, paid developer accounts, and a physical device for testing.

---

## 0. Approach: remote-URL shell (chosen) vs bundled SPA

| | Remote-URL shell (this scaffold) | Bundled SPA |
|---|---|---|
| WebView loads | `https://family.agent-ia.mx` (live) | Assets baked into the app bundle |
| Content updates | Instant via normal web deploy, **no store review** | Every change needs a store resubmission |
| Works with Astro SSR | ✅ Yes — the running Node server keeps serving | ❌ No — SSR needs a server; there is no self-contained SPA |
| Offline | Offline fallback page only | Full offline if built for it |
| Apple risk | Higher (Guideline 4.2 "min functionality" — mitigate with native push/share) | Lower |

**Why remote-URL here:** this frontend is Astro **SSR** (`output: 'server'` in
`frontend/astro.config.mjs`). Auth middleware (`frontend/src/middleware.ts`), the
cookie-forwarding `/api/*` proxies, and per-request rendering all require a
running Node server, so there is no static SPA to embed. The remote-URL shell
loads the same production site everyone else uses, and web deploys ship to the
apps instantly.

The switch is a one-line change: to go bundled later, set `webDir` to a static
build output and delete the `server.url` block in `capacitor.config.ts`. Do that
only if the frontend is re-architected to `output: 'static'`/`'hybrid'`.

---

## 1. Prerequisites (operator's Mac)

- **macOS + Xcode** (latest; from the App Store). Run once: `xcode-select --install`.
- **CocoaPods**: `sudo gem install cocoapods` (or `brew install cocoapods`).
- **Android Studio** with the Android SDK + an emulator or a physical Android device.
- **JDK 17** (bundled with recent Android Studio, or `brew install openjdk@17`).
- **Node 20+** (matches the repo) and npm.
- **Apple Developer Program** — $99/year (needed for device testing beyond 7 days, push, and submission).
- **Google Play Developer** — $25 one-time.
- A **physical iPhone** for testing push (the iOS Simulator cannot receive APNs pushes).

---

## 2. Install the Capacitor toolchain (local, NOT committed)

Run inside `frontend/`. **Do not commit the resulting `package.json` /
`package-lock.json` changes to the CI deploy branch** — they would make `npm ci`
in the web build pull native-only packages. Options, in order of preference:

1. **Native branch** — do all native work on a dedicated `mobile`/`native`
   branch that is never merged into the deploy branch. Commit the native
   projects there if you want them versioned.
2. **Ephemeral install** — `npm install --no-save @capacitor/...` so nothing is
   written to `package.json`. Re-run before each native build session.

```bash
cd frontend

# Core + CLI + platforms + native push
npm install --no-save \
  @capacitor/core \
  @capacitor/cli \
  @capacitor/ios \
  @capacitor/android \
  @capacitor/push-notifications

# Optional but recommended for icons/splash + native UX:
npm install --no-save \
  @capacitor/assets \
  @capacitor/splash-screen \
  @capacitor/app \
  @capacitor/browser \
  @capacitor/share
```

> `@capacitor/browser` matters for auth — see the **Google sign-in gotcha** below.

---

## 3. Initialize & add platforms

`frontend/capacitor.config.ts` already carries `appId` (`mx.agent-ia.family`),
`appName` (`Family Task Manager`), `webDir: 'www'`, and `server.url`. You do
**not** need `npx cap init` (that only regenerates the config) — but if you run
it, keep those values.

Create the minimal `www/` fallback the CLI expects (it is git-ignored; the live
UI comes from `server.url`):

```bash
cd frontend
mkdir -p www
cat > www/index.html <<'HTML'
<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Family Task Manager</title>
<body style="margin:0;background:#4FB8E6;display:grid;place-items:center;height:100vh;font-family:system-ui">
  <p style="color:#fff">Cargando… / Loading…</p>
</body>
HTML
```

Add the native platforms:

```bash
npx cap add ios
npx cap add android
npx cap sync            # copies config + installs native plugin pods/gradle deps
```

This generates `frontend/ios/` and `frontend/android/` (both git-ignored).

---

## 4. App icons & splash (brand)

Reuse the existing brand assets in `frontend/public/` (`icon-512.png`,
`icon-maskable-512.png`). The brand background is **`#4FB8E6`** (`--color-brand-sky`,
see `docs/design-tokens.md`; matches `manifest.webmanifest` `theme_color`).

```bash
cd frontend
# Put a 1024x1024 icon + 2732x2732 splash in ./resources, then:
npx capacitor-assets generate --iconBackgroundColor '#4FB8E6' --splashBackgroundColor '#4FB8E6'
```

---

## 5. Native push wiring (the important part)

### What already exists (Web Push / VAPID) and why it is not enough

The backend push stack is **Web Push over VAPID** (`pywebpush`):

- Table `push_subscriptions` (`backend/app/models/push_subscription.py`) — stores
  a browser `endpoint` + `p256dh`/`auth` keys per `(user, endpoint)`.
- Routes `backend/app/api/routes/push.py`: `GET /api/push/public-key`,
  `POST /api/push/subscribe`, `POST /api/push/unsubscribe`, `GET /api/push/health`.
- Sender `backend/app/services/push_service.py` (`PushService.send_to_user`,
  `fan_out_pending_gig`).
- Frontend: `frontend/src/components/EnablePushButton.astro` calls
  `navigator.serviceWorker` + `PushManager.subscribe(...)`; `frontend/public/sw.js`
  renders `push` / `notificationclick`. SSR proxies at
  `frontend/src/pages/api/push/{public-key,subscribe}.ts`.

**This does not work inside the native shell.** iOS `WKWebView` does not support
the Web Push API or service-worker push, and Android's `WebView` push support is
unreliable. Native apps must use the OS push channels: **APNs** (iOS) and
**FCM** (Android). Capacitor's `@capacitor/push-notifications` gives you an
**APNs device token** on iOS and an **FCM registration token** on Android — these
are *not* Web Push endpoints, so `pywebpush` cannot deliver to them.

You therefore need a **bridge**: register the native token, store it, and send to
it over APNs/FCM.

### 5a. iOS — APNs setup

1. In the **Apple Developer** portal, enable the **Push Notifications** capability
   for the `mx.agent-ia.family` App ID and create an **APNs Auth Key** (`.p8`) —
   note the Key ID and your Team ID.
2. In **Xcode** (`npx cap open ios`), target → *Signing & Capabilities* → add
   **Push Notifications** and **Background Modes → Remote notifications**.
3. Capacitor's iOS push uses APNs directly (no Firebase required), **or** route
   iOS through Firebase too if you want a single sender — decide in 5c.

### 5b. Android — FCM setup

1. Create/reuse a **Firebase** project. Add an Android app with package
   `mx.agent-ia.family`. Download `google-services.json` into
   `frontend/android/app/`.
2. `@capacitor/push-notifications` wires the FCM SDK via Gradle on `cap sync`.
3. Grab the **FCM server credentials** (service-account JSON for the HTTP v1 API)
   for the backend sender.

### 5c. Frontend registration (remote-URL shell)

Because the web app is loaded remotely, `@capacitor/push-notifications` is **not
bundled** into the web build. Two ways to drive it:

- **Global bridge (no web dep, recommended for the shell):** the native runtime
  injects `window.Capacitor`. Add a small progressive-enhancement script to
  `frontend/src/layouts/Layout.astro`, guarded so it is inert in normal browsers:

  ```html
  <script is:inline>
    // Only runs inside the Capacitor native shell; a no-op in web browsers.
    (async () => {
      const Cap = window.Capacitor;
      if (!Cap?.isNativePlatform?.()) return;
      const Push = Cap.Plugins.PushNotifications;
      const perm = await Push.requestPermissions();
      if (perm.receive !== 'granted') return;
      await Push.register();
      Push.addListener('registration', async (t) => {
        // t.value = APNs token (iOS) or FCM token (Android)
        await fetch('/api/push/register-native', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            token: t.value,
            platform: Cap.getPlatform(), // 'ios' | 'android'
          }),
        });
      });
      Push.addListener('pushNotificationActionPerformed', (a) => {
        const url = a?.notification?.data?.url;
        if (url) window.location.assign(url);
      });
    })();
  </script>
  ```

- **Bundled-SPA path only:** import `@capacitor/push-notifications` directly.
  Not applicable to the remote-URL shell.

### 5d. Backend bridge (follow-up work — NOT in this scaffold's scope)

The `/api/push/register-native` endpoint above and an APNs/FCM sender do **not
exist yet**. Shape for a future backend PR (must stay multi-tenant — scope every
query by `family_id`, and gate under `require_feature` if treated as premium):

1. **Store native tokens.** Either add `platform` + `native_token` columns to
   `push_subscriptions` (nullable; web rows keep `endpoint`/`p256dh`/`auth`, native
   rows keep `platform`/`native_token`) via an Alembic migration, or add a sibling
   `native_push_tokens` table. Add `POST /api/push/register-native` +
   `.../unregister-native` mirroring the existing subscribe/unsubscribe handlers.
2. **Send over APNs/FCM.** Extend `PushService.send_to_user` to fan out to *both*
   channels: web endpoints via `pywebpush` (today), native tokens via APNs
   (`.p8` key, e.g. the `apns2`/`aioapns` lib) and FCM HTTP v1 (service account).
   **These libraries are new deps** — add them to `backend/requirements.txt` in
   that PR, not here.
3. **Config.** New env vars alongside the existing `VAPID_*` in
   `backend/app/core/config.py`: `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_KEY_P8`,
   `APNS_BUNDLE_ID=mx.agent-ia.family`, `APNS_USE_SANDBOX`, and
   `FCM_SERVICE_ACCOUNT_JSON` (or `FCM_PROJECT_ID` + creds path).
4. **Simplest alternative:** route *both* iOS and Android through **FCM** (FCM can
   relay to APNs). Then the backend only needs the FCM HTTP v1 sender and one
   `google-services.json` + `GoogleService-Info.plist`. Fewer moving parts.

Until this bridge ships, the native apps still fully work — they just won't
receive push; in-app notifications (`/api/notifications`) continue to function.

---

## 6. Google sign-in gotcha (read before shipping)

Google **blocks its OAuth consent screen inside embedded WebViews**
("this browser or app may not be secure", `disallowed_useragent`). The app's
Google login (`family.agent-ia.mx/auth/google/callback`) will fail if it opens
inside the Capacitor WebView. Mitigations:

- Open OAuth in the **system browser** via `@capacitor/browser`
  (`Browser.open({ url })`) → iOS `ASWebAuthenticationSession` / Android Custom
  Tabs, then deep-link back. This is the standard, Google-approved flow.
- Or offer **email/password** sign-in in-app (already supported) and treat Google
  as browser-only.
- Native "Sign in with Google" SDKs are an alternative but require registering the
  native client IDs. Note the backend already accepts multiple client IDs via
  `GOOGLE_CLIENT_IDS` (`backend/app/services/google_oauth_service.py`), so adding
  an iOS/Android OAuth client under the same Cloud project is supported server-side.

**Apple also requires** that any app offering third-party social login (Google)
must also offer **Sign in with Apple** (Guideline 4.8). Plan for that or drop
in-app Google to avoid rejection.

---

## 7. Build, run, submit

### iOS

```bash
cd frontend
npx cap sync ios
npx cap open ios          # opens Xcode
```

In Xcode: set the **Team** + a unique **Bundle Identifier** (`mx.agent-ia.family`),
bump **Version**/**Build**, select a **real device**, and *Run* to smoke-test.
Then *Product → Archive* → **Distribute App** → **App Store Connect**. Manage
signing certificates + provisioning profiles under your **Apple Developer**
account (let Xcode "automatically manage signing" for the first pass).

### Android

```bash
cd frontend
npx cap sync android
npx cap open android      # opens Android Studio
```

In Android Studio: *Build → Generate Signed Bundle / APK → Android App Bundle
(.aab)*. Create/keep an **upload keystore** (store it securely — losing it blocks
future updates unless you use Play App Signing). Enroll in **Play App Signing**.
Upload the `.aab` to the **Play Console**.

### Store records

- **App Store Connect:** create the app (bundle `mx.agent-ia.family`), fill the
  listing, upload screenshots, complete **App Privacy** (data collection: account,
  usage, financial — the budget feature; declare no tracking), set age rating,
  attach the build, submit for review.
- **Play Console:** create the app, complete **Data safety**, content rating,
  target audience (families → **Families policy** applies since kids use it — be
  precise), store listing, upload the `.aab`, roll out.

---

## 8. ASO / store-listing fields

Store metadata (name, subtitle, keywords, description, screenshots, categories)
is maintained centrally in **[`docs/SEO_ASO.md`](./SEO_ASO.md)** — treat that as
the single source of truth and copy from it into App Store Connect / Play Console.
If that file is not present yet, it is produced by the SEO/ASO task; until then,
seed the listing from these scaffold values and reconcile later:

| Field | Value |
|---|---|
| App name | Family Task Manager — Tareas en familia |
| Bundle / package ID | `mx.agent-ia.family` |
| Primary category | Productivity (secondary: Lifestyle / Family) |
| Locales | **es-MX** (primary, Mexico-first) + **en-US** |
| Short description | Tareas del hogar, premios y presupuesto — en familia. |
| Theme / brand color | `#4FB8E6` (`--color-brand-sky`, `docs/design-tokens.md`) |
| Support URL | https://family.agent-ia.mx |
| Privacy policy URL | (required by both stores — publish one) |

Provide **both ES and EN** localizations for every field (the app is bilingual,
default `es`). Screenshots: capture the standalone PWA/app on device in both
languages. Cross-reference `docs/SEO_ASO.md` for keyword sets, long descriptions,
and the promo text.

---

## 9. Apple Guideline 4.2 (minimum functionality)

A pure website wrapper risks rejection under **4.2**. This scaffold mitigates by
adding genuine native capability:

- **Native push** (§5) — real APNs/FCM notifications.
- Consider adding **native share** (`@capacitor/share`) and **haptics**.
- The app is installable, works offline (fallback page), and is a bona-fide family
  utility, not a marketing site.

Lead the review notes with these native features and a demo login
(see `CLAUDE.md` demo credentials, e.g. `mom@demo.com / password123`).

---

## 10. Update flow after launch

- **Web/content changes:** deploy the site as usual (`scripts/deploy-onprem.sh`).
  The remote-URL shell picks them up on next launch — **no store review**.
- **Native shell changes** (new plugin, icon, push wiring, config): rebuild in
  Xcode / Android Studio and resubmit. Bump the build number each time.
- Do **not** change the app's core purpose via remote content — Apple's Guideline
  2.3.1 / 4.2 apply to what the shell ultimately does.

---

## Quick reference

| Item | Value / location |
|---|---|
| appId / bundle | `mx.agent-ia.family` |
| appName | Family Task Manager |
| Config | `frontend/capacitor.config.ts` (inert; excluded from `tsconfig.json`) |
| Remote URL | `https://family.agent-ia.mx` |
| API host | `https://api-family.agent-ia.mx` |
| Native projects | `frontend/ios/`, `frontend/android/` (git-ignored) |
| webDir fallback | `frontend/www/index.html` (git-ignored) |
| Existing push (web) | `backend/app/api/routes/push.py`, `push_service.py`, `frontend/public/sw.js` |
| Push bridge (todo) | `/api/push/register-native` + APNs/FCM sender (future backend PR) |
| Brand color | `#4FB8E6` (`docs/design-tokens.md`) |
| ASO source of truth | `docs/SEO_ASO.md` |
