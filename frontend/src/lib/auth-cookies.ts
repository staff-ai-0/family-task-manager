const ACCESS_MAX_AGE = 60 * 60;            // 1 hour
const REFRESH_MAX_AGE = 60 * 60 * 24 * 30;  // 30 days (sliding: renewed on every use)
const SWITCHED_REFRESH_MAX_AGE = 60 * 60 * 2; // 2 hours (profile-switched kid sessions)
const HOME_MAX_AGE = 60 * 60 * 24 * 30;     // 30 days, same as the parent refresh token
const HOME_PATH = "/api/auth/profile";

function buildCookie(
    name: string,
    value: string,
    opts: { maxAge: number; httpOnly?: boolean; secure: boolean; path?: string }
): string {
    let c = `${name}=${encodeURIComponent(value)}`;
    c += `; Path=${opts.path ?? "/"}`;
    if (opts.httpOnly) c += "; HttpOnly";
    if (opts.secure) c += "; Secure";
    c += "; SameSite=Lax";
    c += `; Max-Age=${opts.maxAge}`;
    return c;
}

/** Set-Cookie header values for the access+refresh pair. Both httpOnly,
 *  Path=/ so the middleware/proxies (which run on every route) can read the
 *  refresh cookie to mint a fresh access token. */
export function authCookies(accessToken: string, refreshToken: string, secure: boolean, switched = false): string[] {
    return [
        buildCookie("access_token", accessToken, { maxAge: ACCESS_MAX_AGE, httpOnly: true, secure }),
        buildCookie("refresh_token", refreshToken, { maxAge: switched ? SWITCHED_REFRESH_MAX_AGE : REFRESH_MAX_AGE, httpOnly: true, secure }),
    ];
}

/** Set-Cookie header values that clear both auth cookies (HTTP + HTTPS). */
export function clearAuthCookies(): string[] {
    return [
        "access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        "access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Secure",
        "refresh_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        "refresh_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Secure",
    ];
}

/** The parent's "home" refresh token for the shared-device profile switcher.
 *  SECURITY: this is an ordinary PARENT refresh token. It must stay httpOnly and
 *  scoped to Path=/api/auth/profile (RFC 6265: matches /api/auth/profile/switch,
 *  NOT /api/auth/profile-switch or /api/auth/refresh), so it never rides on
 *  normal requests or kid sessions. Nothing else may read or forward it. */
export function homeCookie(value: string, secure: boolean): string {
    return buildCookie("ftm_home", value, { maxAge: HOME_MAX_AGE, httpOnly: true, secure, path: HOME_PATH });
}

/** Set-Cookie values that clear ftm_home (HTTP + HTTPS). */
export function clearHomeCookie(): string[] {
    return [
        `ftm_home=; Path=${HOME_PATH}; HttpOnly; SameSite=Lax; Max-Age=0`,
        `ftm_home=; Path=${HOME_PATH}; HttpOnly; SameSite=Lax; Max-Age=0; Secure`,
    ];
}

/** UX hint that this browser holds a profile-switched (kid) session. NOT httpOnly
 *  and never an authorization input. */
export function switchedMarker(secure: boolean): string {
    return buildCookie("ftm_sw", "1", { maxAge: SWITCHED_REFRESH_MAX_AGE, secure });
}

/** ui_role cookie (UI mode hint read by Layout), same shape login uses. */
export function uiRoleCookie(role: unknown, secure: boolean): string[] {
    const r = String(role || "").toLowerCase();
    if (!r) return [];
    return [`ui_role=${r}; Path=/; Max-Age=${60 * 60 * 24 * 7}; SameSite=Lax${secure ? "; Secure" : ""}`];
}

export function clearSwitchedMarker(): string[] {
    return [
        "ftm_sw=; Path=/; SameSite=Lax; Max-Age=0",
        "ftm_sw=; Path=/; SameSite=Lax; Max-Age=0; Secure",
    ];
}
