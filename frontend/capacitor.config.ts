// -----------------------------------------------------------------------------
// Capacitor configuration — App Store / Play Store native shell
// -----------------------------------------------------------------------------
//
// SCAFFOLD ONLY. This file is committed so the native wrap is reproducible, but
// the @capacitor/* toolchain is NOT installed in this repo's package.json (that
// would pull heavy native-only deps into the CI `npm ci` web build). The
// operator installs the toolchain on a Mac and runs `npx cap ...` — see
// docs/CAPACITOR.md for the full runbook.
//
// This module is intentionally INERT for the web build:
//   * It imports nothing from @capacitor/cli, so `astro check` / `astro build`
//     never fail on a missing module.
//   * It is listed in frontend/tsconfig.json `exclude`, so the Astro type
//     checker skips it entirely.
//   * Nothing in src/ imports it — Vite/Astro never bundle it.
// The Capacitor CLI loads it directly (via its own ts loader) at native-build
// time; it only needs a default-exported config object.
//
// Once the operator has run `npm install @capacitor/cli` locally they MAY
// restore full typing by uncommenting the two lines below and appending
// `satisfies CapacitorConfig` to the object — but it is not required.
//
//   import type { CapacitorConfig } from '@capacitor/cli';
//
// -----------------------------------------------------------------------------

// APPROACH: remote-URL shell.
// The native app is a thin WebView that loads the live production site. Content
// updates ship instantly via the normal web deploy (no store review) — only
// changes to the native shell itself require resubmission. `webDir` is still
// required by the CLI (used for `cap copy` and as the offline fallback), so keep
// a minimal frontend/www/index.html around (see docs/CAPACITOR.md).
//
// ALTERNATIVE: bundled SPA.
// You could instead ship the web assets inside the app bundle by setting
// `webDir` to a static build and DELETING the `server.url` block. That is NOT
// recommended here: this frontend is Astro SSR (`output: 'server'` in
// astro.config.mjs) — auth middleware, the `/api/*` cookie-forwarding proxies,
// and per-request rendering all need a running Node server, so there is no
// self-contained SPA to bundle. Keep the remote-URL shell unless the app is
// re-architected to static/hybrid output.

const config = {
  appId: 'mx.agent-ia.family',
  appName: 'Family Task Manager',

  // Required by the CLI. In remote-URL mode this only backs `cap copy` and the
  // offline fallback screen; the live UI comes from server.url below.
  webDir: 'www',

  // Load the canonical production site inside the native WebView.
  server: {
    url: 'https://family.agent-ia.mx',
    cleartext: false,
    // Hosts the WebView is allowed to navigate to without kicking out to the
    // system browser. Include the API host and OAuth providers. NOTE: Google
    // blocks its OAuth consent screen inside embedded WebViews — see the
    // "Google sign-in gotcha" section in docs/CAPACITOR.md before relying on it.
    allowNavigation: [
      'family.agent-ia.mx',
      'api-family.agent-ia.mx',
    ],
  },

  ios: {
    // Let the web content manage its own safe-area insets (the site already
    // handles notch/home-indicator padding).
    contentInset: 'always',
    // Match the brand sky background so the launch/scroll bounce isn't white.
    backgroundColor: '#4FB8E6',
  },

  android: {
    backgroundColor: '#4FB8E6',
    // Play requires HTTPS; never allow cleartext in the shipped shell.
    allowMixedContent: false,
  },

  plugins: {
    // Native push. On iOS this yields an APNs device token; on Android an FCM
    // token. These are NOT Web Push endpoints — the existing VAPID/pywebpush
    // backend cannot deliver to them directly. See "Native push wiring" in
    // docs/CAPACITOR.md for the required APNs/FCM bridge.
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
    // Optional splash tuning if @capacitor/splash-screen is added later.
    SplashScreen: {
      launchAutoHide: true,
      backgroundColor: '#4FB8E6',
      showSpinner: false,
    },
  },
};

export default config;
