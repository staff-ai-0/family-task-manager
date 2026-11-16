import type { APIRoute } from "astro";
import {
    clearAuthCookies,
    clearHomeCookie,
    clearSharedHint,
    clearSwitchedMarker,
} from "../../../lib/auth-cookies";

/**
 * POST /api/auth/logout
 * Best-effort revokes the session server-side (bumps token_version,
 * logging out everywhere), then clears both auth cookies + ui_role.
 *
 * Profile switcher: a switched (kid) session (ftm_sw present) clears the
 * ordinary cookies and returns to /profiles, keeping the parent's ftm_home
 * and the ftm_shared hint. A normal logout also clears both, so the device
 * stops being shared. (ftm_sw is a UX hint only; the backend decides what a
 * token may do.)
 */
export const POST: APIRoute = async ({ cookies }) => {
    const switched = cookies.get("ftm_sw")?.value === "1";
    // Bump token_version server-side (logout-everywhere) before clearing cookies.
    const access = cookies.get("access_token")?.value;
    if (access) {
        const api = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";
        try {
            await fetch(`${api}/api/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${access}` } });
        } catch { /* best-effort; still clear cookies below */ }
    }
    const headers = new Headers({ Location: switched ? "/profiles" : "/login" });
    for (const c of clearAuthCookies()) headers.append("Set-Cookie", c);
    if (!switched) {
        for (const c of [...clearHomeCookie(), ...clearSharedHint()]) headers.append("Set-Cookie", c);
    }
    for (const c of clearSwitchedMarker()) headers.append("Set-Cookie", c);
    headers.append("Set-Cookie", "ui_role=; Path=/; SameSite=Lax; Max-Age=0");
    headers.append("Set-Cookie", "ui_role=; Path=/; SameSite=Lax; Max-Age=0; Secure");
    return new Response(null, { status: 302, headers });
};
