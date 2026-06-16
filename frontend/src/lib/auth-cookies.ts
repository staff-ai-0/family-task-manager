const ACCESS_MAX_AGE = 60 * 60;            // 1 hour
const REFRESH_MAX_AGE = 60 * 60 * 24 * 7;  // 7 days

function buildCookie(
    name: string,
    value: string,
    opts: { maxAge: number; httpOnly?: boolean; secure: boolean }
): string {
    let c = `${name}=${encodeURIComponent(value)}`;
    c += "; Path=/";
    if (opts.httpOnly) c += "; HttpOnly";
    if (opts.secure) c += "; Secure";
    c += "; SameSite=Lax";
    c += `; Max-Age=${opts.maxAge}`;
    return c;
}

/** Set-Cookie header values for the access+refresh pair. Both httpOnly,
 *  Path=/ so the middleware/proxies (which run on every route) can read the
 *  refresh cookie to mint a fresh access token. */
export function authCookies(accessToken: string, refreshToken: string, secure: boolean): string[] {
    return [
        buildCookie("access_token", accessToken, { maxAge: ACCESS_MAX_AGE, httpOnly: true, secure }),
        buildCookie("refresh_token", refreshToken, { maxAge: REFRESH_MAX_AGE, httpOnly: true, secure }),
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
