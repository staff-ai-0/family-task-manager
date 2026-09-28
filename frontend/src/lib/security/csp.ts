// ---------------------------------------------------------------------------
// Security headers (WS-F1). Starter CSP notes:
// - The browser talks to the backend ONLY through same-origin Astro proxy
//   routes (/api/*, /uploads/*) — no page fetches api-family.agent-ia.mx
//   directly — so connect-src stays 'self' plus accounts.google.com (Google
//   Identity Services pings its own origin from the GSI client script).
// - Astro emits inline <script> tags → script-src needs 'unsafe-inline'.
// - Google Sign-In: script + iframe + stylesheet from accounts.google.com.
// - Fonts: Google Fonts stylesheet (fonts.googleapis.com) + files (gstatic).
// - img-src blob:/data: for camera-capture previews (receipt/proof upload).
// - frame-ancestors 'none' + X-Frame-Options DENY: nothing embeds this app
//   (the kiosk page is opened directly, never iframed).
// - Cloudflare Web Analytics (cookieless page views + Web Vitals, injected by
//   Cloudflare at the edge): beacon script from static.cloudflareinsights.com,
//   reports to cloudflareinsights.com. Disclosed in /privacidad (UX-A).
// CSP is only sent in production: dev needs Vite HMR websockets/eval, and
// guarding it here keeps local DX untouched.
export const CSP = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://accounts.google.com https://static.cloudflareinsights.com",
    "style-src 'self' 'unsafe-inline' https://accounts.google.com https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "connect-src 'self' https://accounts.google.com https://cloudflareinsights.com",
    "frame-src https://accounts.google.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
].join("; ");
