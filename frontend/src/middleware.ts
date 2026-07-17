import { createHash } from "node:crypto";
import { defineMiddleware } from "astro:middleware";
import type { User } from "./types/api";

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
// CSP is only sent in production: dev needs Vite HMR websockets/eval, and
// guarding it here keeps local DX untouched.
const CSP = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://accounts.google.com",
    "style-src 'self' 'unsafe-inline' https://accounts.google.com https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "connect-src 'self' https://accounts.google.com",
    "frame-src https://accounts.google.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
].join("; ");

// ---------------------------------------------------------------------------
// Short-TTL auth context cache (WS-perf). Before this, EVERY proxied /api/*
// request cost two extra backend round-trips (/api/auth/me +
// /api/subscriptions/current) before the real call — 3x amplification.
//
// Safety model: the backend validates the JWT on the real proxied request
// anyway; this middleware check is a redundant pre-check whose only products
// are context.locals.user/plan (role gates in a few Astro API routes, plan
// upsell UI). Serving those from a cache for up to AUTH_CACHE_TTL_SECONDS
// (default 30s, 0 disables) means a just-revoked token or just-changed plan
// can be reflected stale for that window in locals — never in actual backend
// authorization. Keyed by SHA-256 of the token so raw tokens never sit in the
// map; a refresh mints a new token and therefore a new key.
const AUTH_CACHE_TTL_MS =
    (Number(process.env.AUTH_CACHE_TTL_SECONDS ?? "30") || 0) * 1000;
const AUTH_CACHE_MAX_ENTRIES = 500;
type AuthCacheEntry = { user: User; plan: unknown; expires: number };
const authCache = new Map<string, AuthCacheEntry>();

function authCacheKey(token: string): string {
    return createHash("sha256").update(token).digest("hex");
}

function authCacheGet(key: string): AuthCacheEntry | undefined {
    const hit = authCache.get(key);
    if (!hit) return undefined;
    if (hit.expires <= Date.now()) {
        authCache.delete(key);
        return undefined;
    }
    return hit;
}

function authCacheSet(key: string, user: User, plan: unknown): void {
    if (AUTH_CACHE_TTL_MS <= 0) return;
    // Cheap size cap: evict the oldest insertion (Map preserves order).
    if (authCache.size >= AUTH_CACHE_MAX_ENTRIES) {
        const oldest = authCache.keys().next().value;
        if (oldest !== undefined) authCache.delete(oldest);
    }
    authCache.set(key, { user, plan, expires: Date.now() + AUTH_CACHE_TTL_MS });
}

function withSecurityHeaders(response: Response): Response {
    const h = response.headers;
    h.set("X-Content-Type-Options", "nosniff");
    h.set("Referrer-Policy", "strict-origin-when-cross-origin");
    if (!import.meta.env.DEV) {
        h.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
    }
    // Page-level headers only make sense on HTML documents.
    if ((h.get("content-type") ?? "").includes("text/html")) {
        h.set("X-Frame-Options", "DENY");
        if (!import.meta.env.DEV) h.set("Content-Security-Policy", CSP);
    }
    return response;
}

/**
 * Decode a JWT locally and decide whether it is expired (or unusable).
 * Refreshes 30s early to avoid edge races near the boundary.
 */
function isExpired(jwt: string | undefined): boolean {
    if (!jwt) return true;
    const parts = jwt.split(".");
    if (parts.length !== 3) return true;
    try {
        const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
        if (!payload.exp) return true;
        // Refresh 30s early to avoid edge races.
        return Date.now() / 1000 >= payload.exp - 30;
    } catch {
        return true;
    }
}

/**
 * Middleware for authentication checks and request logging
 */
export const onRequest = defineMiddleware(async (context, next) => {
    const { url, cookies, redirect, request } = context;
    const path = url.pathname;

    // Log all requests in development
    if (import.meta.env.DEV) {
        console.log(`[${request.method}] ${path}`);
    }

    // CSRF Protection for state-changing requests
    // Check CSRF BEFORE authentication check for all non-GET API requests
    if (request.method !== "GET" && path.startsWith("/api/")) {
        const origin = request.headers.get("origin");
        const host = request.headers.get("host");
        
        // Allow null origin for server-side requests (Astro API routes calling backend)
        // This happens when our own API routes make server-to-server requests
        // We only skip the CSRF check; auth checks below still apply
        if (origin !== null) {
            // In development, allow localhost origins
            if (import.meta.env.DEV) {
                const devOrigins = [
                    `http://${host}`,
                    `https://${host}`,
                    "http://localhost:3000",
                    "http://localhost:3003",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:3003"
                ];
                if (!devOrigins.includes(origin)) {
                    console.error(`CSRF violation in dev: origin ${origin} not in allowed list for ${path}`);
                    return withSecurityHeaders(new Response(
                        JSON.stringify({ detail: "CSRF validation failed" }),
                        { status: 403, headers: { "Content-Type": "application/json" } }
                    ));
                }
            } else {
                // In production, strictly enforce same-origin or allowed hosts
                const allowedHosts = ["family.agent-ia.mx", host];
                const originHost = origin.replace(/^https?:\/\//, "");
                
                if (!allowedHosts.includes(originHost)) {
                    console.error(`CSRF violation: origin ${origin} (host: ${originHost}) does not match allowed hosts: ${allowedHosts.join(', ')}`);
                    return withSecurityHeaders(new Response(
                        JSON.stringify({ detail: "CSRF validation failed" }),
                        { status: 403, headers: { "Content-Type": "application/json" } }
                    ));
                }
            }
        }
    }

    // Always allow static assets (CSS, JS, images, fonts)
    if (path.startsWith("/_astro/") || path.startsWith("/favicon") || path.match(/\.(css|js|png|svg|ico|woff2?|ttf|otf)$/)) {
        return withSecurityHeaders(await next());
    }

    // Anonymous-visitor locale: if no lang cookie exists yet, derive one from
    // Accept-Language (first es*/en* tag wins; anything else — or no header —
    // defaults to "es", Mexico-first) and SET the cookie so every downstream
    // page resolves the same language instead of each page guessing its own
    // fallback. Attributes mirror /api/lang (not httpOnly — client scripts
    // read document.cookie for lang). Only set on HTML page requests — API and
    // proxy routes must not grow a Set-Cookie on every JSON/binary response
    // (assets already returned early above).
    const isPageRequest = !path.startsWith("/api/") && !path.startsWith("/uploads/");
    if (isPageRequest && !cookies.get("lang")?.value) {
        const acceptLanguage = request.headers.get("accept-language") ?? "";
        let lang = "es";
        for (const part of acceptLanguage.split(",")) {
            const tag = part.split(";")[0].trim().toLowerCase();
            if (tag.startsWith("es")) break; // lang already "es"
            if (tag.startsWith("en")) {
                lang = "en";
                break;
            }
        }
        cookies.set("lang", lang, {
            path: "/",
            maxAge: 60 * 60 * 24 * 365,
            sameSite: "lax",
            secure: !import.meta.env.DEV, // match auth cookie flags
        });
    }

    // Public routes that don't require authentication
    const publicRoutes = [
        "/",
        "/login",
        "/register",
        "/forgot-password",
        "/verify-email",
        "/reset-password",
        "/accept-invitation",
        "/help",   // English user guide — linked from welcome email
        "/ayuda",  // Spanish user guide — linked from welcome email
        "/privacidad",  // Aviso de Privacidad (bilingual) — legal, must be public
        "/terminos",    // Términos y Condiciones (bilingual) — legal, must be public
        "/tdah",        // TDAH/rutinas content landing — marketing, must be crawlable
        "/rutinas",     // ES keyword alias → 301s to /tdah (still needs to be public)
        "/sitemap.xml", // SEO — crawlable without auth
        "/robots.txt",  // SEO — crawlable without auth
        "/api/auth/login",
        "/api/auth/refresh",  // BFF refresh route — callable even when the access token is dead
        "/api/auth/register",  // Frontend API route for registration (calls backend /api/auth/register-family)
        "/api/auth/register-family",  // Backend API route (for direct calls)
        "/api/auth/verify-email",
        "/api/auth/resend-verification",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/check-methods",  // Used by login form to detect Google-only accounts before prompting for password
        "/api/oauth/google",
        "/api/lang",
        "/api/oauth/google/",
        "/api/invitations/accept", // Only public endpoint is accepting an invitation (no auth needed)
        "/kiosk",  // Wall display — token gated via ?token=...
        "/api/kiosk/snapshot",
        "/api/kiosk/pin-view",  // Kiosk per-kid PIN view — device token in body, PIN-scoped
    ];
    const isPublicRoute = publicRoutes.some(route => path === route || path.startsWith("/api/translate"));

    if (isPublicRoute) {
        const response = await next();
        // /login uses Google Identity Services popup sign-in. Chrome's
        // default COOP (`unsafe-none` or no header) can still block the
        // window.postMessage bridge from the Google popup back to our
        // opener — GIS logs "Cross-Origin-Opener-Policy policy would
        // block the window.postMessage call" and the callback never
        // fires. `same-origin-allow-popups` is the Google-recommended
        // setting for sites that embed GIS.
        if (path === "/login") {
            response.headers.set(
                "Cross-Origin-Opener-Policy",
                "same-origin-allow-popups"
            );
            response.headers.set(
                "Cross-Origin-Embedder-Policy",
                "unsafe-none"
            );
        }
        return withSecurityHeaders(response);
    }

    // Genuinely-unmatched page paths fall through to Astro's custom 404
    // instead of bouncing anonymous visitors to /login. When no file-based
    // route matches, Astro resolves the request to the /404 route, so
    // routePattern is an authoritative "this is not a known page" signal —
    // real protected pages (e.g. /dashboard) never match it and still hit
    // the auth redirect below. API paths keep their JSON 401 contract.
    if (!path.startsWith("/api/") && context.routePattern === "/404") {
        return withSecurityHeaders(await next());
    }

    // Check authentication for protected routes
    let accessToken = cookies.get("access_token")?.value;
    const refreshToken = cookies.get("refresh_token")?.value;
    let refreshedSetCookies: string[] | undefined;

    // Transparently refresh the access token when it's missing/expired but a
    // refresh cookie is present. Runs BEFORE the missing-token guard so a dead
    // access token does not bounce the user to /login if the refresh succeeds.
    if (isExpired(accessToken) && refreshToken) {
        const { refreshAccessToken } = await import("./lib/server/refresh");
        const r = await refreshAccessToken(refreshToken);
        if (r.ok) {
            accessToken = r.accessToken;
            refreshedSetCookies = r.setCookies;
            // Make the fresh token visible to this same request's downstream logic.
            cookies.set("access_token", r.accessToken!, {
                path: "/",
                httpOnly: true,
                sameSite: "lax",
                secure: !import.meta.env.DEV,
                maxAge: 3600,
            });
        }
    }

    if (!accessToken) {
        // Plain log works for both dev and prod. The previous prod branch
        // tried to enumerate cookies via `[...cookies]`, but AstroCookies
        // isn't iterable in the Astro 5 prod SSR build and the spread
        // threw `TypeError: cookies is not iterable` — which turned every
        // unauthenticated request to a protected route into a 500 instead
        // of the intended 302 redirect to /login.
        console.log(`No access_token for protected route: ${path}`);
        // The refresh cookie (if any) is stale/unusable — clear both cookies.
        const { clearAuthCookies } = await import("./lib/auth-cookies");
        // Redirect to login for HTML pages. Carry the intended destination as
        // ?next= so login can resume there after auth (e.g. the kiosk wall
        // tablet's "Scan a flyer" button → /calendar/scan). login.astro
        // validates it as a same-origin relative path before honoring it.
        if (!path.startsWith("/api/")) {
            const next = encodeURIComponent(path + url.search);
            const response = redirect(`/login?next=${next}`, 302);
            for (const c of clearAuthCookies()) response.headers.append("Set-Cookie", c);
            return withSecurityHeaders(response);
        }
        // Return 401 for API routes
        const headers = new Headers({ "Content-Type": "application/json" });
        for (const c of clearAuthCookies()) headers.append("Set-Cookie", c);
        return withSecurityHeaders(new Response(
            JSON.stringify({ detail: "Unauthorized" }),
            { status: 401, headers }
        ));
    }

    // Verify token is valid by checking with backend for API routes
    // For page routes, we'll let the page components handle token validation
    if (path.startsWith("/api/") && path !== "/api/auth/login") {
        // Cache fast-path: skip both backend round-trips when this token's
        // auth context is still fresh (see AUTH_CACHE_TTL_MS above).
        const cacheKey = AUTH_CACHE_TTL_MS > 0 ? authCacheKey(accessToken) : null;
        if (cacheKey) {
            const hit = authCacheGet(cacheKey);
            if (hit) {
                context.locals.user = hit.user;
                context.locals.token = accessToken;
                if (hit.plan) context.locals.plan = hit.plan;
                const response = await next();
                if (refreshedSetCookies) {
                    for (const c of refreshedSetCookies) response.headers.append("Set-Cookie", c);
                }
                return withSecurityHeaders(response);
            }
        }
        try {
            const apiUrl = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";
            const response = await fetch(`${apiUrl}/api/auth/me`, {
                headers: {
                    "Authorization": `Bearer ${accessToken}`,
                },
            });

            if (!response.ok) {
                // Only treat 401/403 as "token is bad" — those are authoritative
                // signals from the auth check. 5xx / 502 / 504 / etc. are likely
                // transient (backend restart, deploy, proxy hiccup) and the
                // user's token may be perfectly valid. Surface a 503 without
                // wiping the cookie so the user can retry.
                if (response.status === 401 || response.status === 403) {
                    // The (possibly just-refreshed) access token is still
                    // rejected — drop any cached context for it and clear both
                    // cookies so the client re-auths.
                    if (cacheKey) authCache.delete(cacheKey);
                    const { clearAuthCookies } = await import("./lib/auth-cookies");
                    const headers = new Headers({ "Content-Type": "application/json" });
                    for (const c of clearAuthCookies()) headers.append("Set-Cookie", c);
                    return withSecurityHeaders(new Response(
                        JSON.stringify({ detail: "Invalid or expired token" }),
                        { status: 401, headers }
                    ));
                }
                return withSecurityHeaders(new Response(
                    JSON.stringify({
                        detail: "Backend temporarily unavailable. Retry shortly.",
                        code: "backend_error",
                    }),
                    { status: 503, headers: { "Content-Type": "application/json" } }
                ));
            }

            const user: User = await response.json();

            // Attach user to context for use in endpoints
            context.locals.user = user;
            context.locals.token = accessToken;

            // Fetch family plan for premium gating
            try {
                const planResponse = await fetch(`${apiUrl}/api/subscriptions/current`, {
                    headers: { "Authorization": `Bearer ${accessToken}` },
                });
                if (planResponse.ok) {
                    context.locals.plan = await planResponse.json();
                }
            } catch {
                // Plan fetch failure is non-fatal — default to free
            }

            if (cacheKey) {
                authCacheSet(cacheKey, user, context.locals.plan ?? null);
            }
        } catch (error) {
            // fetch() throws only on NETWORK failures (DNS, connection refused,
            // timeout) — never on HTTP errors (those reach line 147 via !response.ok).
            // The token may be perfectly valid; the backend just isn't reachable.
            // Surface that clearly and DO NOT delete the cookie.
            console.error("Backend unreachable during auth check:", error);
            return withSecurityHeaders(new Response(
                JSON.stringify({
                    detail: "Backend temporarily unavailable. Retry shortly.",
                    code: "backend_unreachable",
                }),
                { status: 503, headers: { "Content-Type": "application/json" } }
            ));
        }
    }

    const response = await next();
    // Persist the rotated access+refresh cookies (if we refreshed above) so the
    // browser stores the new pair for subsequent requests.
    if (refreshedSetCookies) {
        for (const c of refreshedSetCookies) response.headers.append("Set-Cookie", c);
    }
    return withSecurityHeaders(response);
});
