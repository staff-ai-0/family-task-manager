/**
 * Pure request-classification rules used by src/middleware.ts.
 *
 * These live outside the middleware so they can be unit-tested without the
 * `astro:middleware` virtual module, which only exists inside an Astro build.
 * Everything here is a pure function of its arguments — no cookies, no fetches,
 * no environment reads — so a test can pin the security decision itself rather
 * than a mock of the surrounding handler.
 *
 * That matters because this is the security-load-bearing part of the request
 * path: the CSRF origin check, which routes bypass auth entirely, and which
 * surfaces count as admin. Before these were extracted, the CSRF check could
 * have been inverted and every automated signal in the repo would have stayed
 * green.
 */

/** Routes reachable without an access token. */
export const PUBLIC_ROUTES: readonly string[] = [
    "/",
    "/login",
    "/register",
    "/forgot-password",
    "/verify-email",
    "/reset-password",
    "/accept-invitation",
    "/help",        // English user guide — linked from welcome email
    "/ayuda",       // Spanish user guide — linked from welcome email
    "/privacidad",  // Aviso de Privacidad (bilingual) — legal, must be public
    "/terminos",    // Términos y Condiciones (bilingual) — legal, must be public
    "/tdah",        // TDAH/rutinas content landing — marketing, must be crawlable
    "/rutinas",     // ES keyword alias → 301s to /tdah (still needs to be public)
    "/sitemap.xml", // SEO — crawlable without auth
    "/robots.txt",  // SEO — crawlable without auth
    "/api/auth/login",
    "/api/auth/refresh",  // BFF refresh route — callable even when the access token is dead
    "/api/auth/register",
    "/api/auth/register-family",
    "/api/auth/verify-email",
    "/api/auth/resend-verification",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/check-methods",  // login form detects Google-only accounts before prompting
    "/api/oauth/google",
    "/api/lang",
    "/api/oauth/google/",
    "/api/invitations/accept",  // accepting an invitation is the only public invitation route
    "/kiosk",                   // Wall display — token gated via ?token=...
    "/api/kiosk/snapshot",
    "/api/kiosk/pin-view",      // device token in body, PIN-scoped
];

/** Origins always accepted in dev, regardless of the request's Host. */
const DEV_ORIGINS: readonly string[] = [
    "http://localhost:3000",
    "http://localhost:3003",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3003",
];

/** The canonical production origin. */
const PROD_HOST = "family.agent-ia.mx";

export function isPublicRoute(path: string): boolean {
    // The /api/translate prefix is public wholesale (guide pages translate
    // content before the reader has an account).
    return PUBLIC_ROUTES.includes(path) || path.startsWith("/api/translate");
}

export function isAdminSurface(path: string): boolean {
    return (
        path === "/admin" ||
        path.startsWith("/admin/") ||
        path === "/api/admin" ||
        path.startsWith("/api/admin/")
    );
}

/** State-changing API calls are the CSRF-relevant ones; GETs are not. */
export function requiresCsrfCheck(method: string, path: string): boolean {
    return method !== "GET" && path.startsWith("/api/");
}

/**
 * Decide whether an Origin may make a state-changing request.
 *
 * A null Origin is allowed: our own Astro API routes call the backend
 * server-side and send none. That only skips CSRF — the auth checks still run.
 */
export function isAllowedOrigin(
    origin: string | null,
    host: string | null,
    isDev: boolean,
): boolean {
    if (origin === null) return true;
    if (isDev) {
        return [`http://${host}`, `https://${host}`, ...DEV_ORIGINS].includes(origin);
    }
    // Compare hosts, not full origins: the scheme is fixed by the tunnel.
    const originHost = origin.replace(/^https?:\/\//, "");
    return [PROD_HOST, host].includes(originHost);
}

/**
 * Page-prefix → togglable module key (families.enabled_modules).
 *
 * Only these prefixes are module-gated; settings and core surfaces never
 * appear here, so switching a module off can never lock a family out of
 * tasks, rewards or their own settings.
 */
export function moduleForPath(path: string): string | null {
    if (path.startsWith("/meals")) return "meals";
    if (path.startsWith("/shopping")) return "shopping";
    if (path.startsWith("/calendar")) return "calendar";
    if (path.startsWith("/pet")) return "pet";
    if (path.startsWith("/chat") || path.startsWith("/dm")) return "chat";
    if (path.startsWith("/budget") || path.startsWith("/envelopes")) return "budget";
    if (
        path.startsWith("/gigs") ||
        path.startsWith("/bank") ||
        path.startsWith("/parent/gigs") ||
        path.startsWith("/parent/payouts")
    ) return "gigs";
    return null;
}

/**
 * Where a deep link into a disabled module should land, or null to allow it.
 *
 * Fails OPEN on a missing or malformed enabled_modules list: gating is a UX
 * affordance, not a security boundary (the backend APIs stay live either way),
 * so an unreadable /auth/me must not lock a family out of a module they have.
 */
export function moduleRedirectTarget(
    path: string,
    user: { enabled_modules?: unknown; role?: unknown } | null | undefined,
): string | null {
    const gated = moduleForPath(path);
    if (!gated) return null;

    const enabled = user?.enabled_modules;
    // NULL enabled_modules means "all modules on" (see families.enabled_modules).
    if (!Array.isArray(enabled)) return null;
    if (enabled.includes(gated)) return null;

    // Parents land on /parent (their dashboard view merged there), kids on
    // /dashboard.
    const home = String(user?.role ?? "").toLowerCase() === "parent"
        ? "/parent"
        : "/dashboard";
    return `${home}?module_off=1`;
}

/**
 * Is this JWT expired (or unusable)?
 *
 * Treats 30s before `exp` as expired to avoid races at the boundary, and
 * treats anything unparseable as expired — failing closed, so a malformed
 * token triggers a refresh rather than being trusted.
 */
/**
 * Routes where minting a fresh token pair is wrong, not merely wasteful.
 *
 * Everything here writes the auth cookies itself. Since the middleware appends
 * its refreshed Set-Cookie headers AFTER the route's own, a refresh on one of
 * these would land last and win — signing the visitor back into the *previous*
 * session on the very request that was meant to change it. That is a silent
 * account mix-up on a shared device, not a slow page.
 */
const NO_REFRESH_ROUTES: readonly string[] = [
    "/api/auth/refresh",       // IS the refresh — refreshing here would recurse
    "/api/auth/logout",        // a fresh pair on the way out defeats the logout
    "/api/auth/login",         // mints its own pair
    "/api/auth/register",      // ditto
    "/api/auth/register-family",
    "/api/oauth/google",
    "/api/oauth/google/",
    "/api/invitations/accept",
];

/**
 * Should this request try to trade the refresh cookie for a fresh access token?
 *
 * Deliberately independent of whether the route is public. The PWA's start_url
 * is "/", which is public: when the refresh only ran on protected routes, every
 * cold launch more than an hour after last use (access_token Max-Age=3600) found
 * no access token, fell through to the marketing landing page, and made the user
 * sign in with Google again — while a valid 30-day refresh cookie sat unread.
 *
 * The refresh-cookie requirement is what keeps this cheap: an anonymous visitor
 * on a public page carries no refresh cookie and so costs no backend call.
 */
export function shouldAttemptRefresh(
    path: string,
    accessToken: string | undefined,
    refreshToken: string | undefined,
    nowMs: number = Date.now(),
): boolean {
    if (!refreshToken) return false;
    if (NO_REFRESH_ROUTES.includes(path)) return false;
    return isJwtExpired(accessToken, nowMs);
}

export function isJwtExpired(jwt: string | undefined, nowMs: number = Date.now()): boolean {
    if (!jwt) return true;
    const parts = jwt.split(".");
    if (parts.length !== 3) return true;
    try {
        const payload = JSON.parse(
            atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")),
        );
        if (!payload.exp) return true;
        return nowMs / 1000 >= payload.exp - 30;
    } catch {
        return true;
    }
}
