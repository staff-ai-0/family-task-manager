import type { APIRoute } from "astro";
import {
    authCookies,
    homeCookie,
    sharedHintCookie,
    switchedMarker,
    uiRoleCookie,
} from "../../../../lib/auth-cookies";
import { callProfile, errorFrom, json } from "../../../../lib/server/profile-proxy";

/**
 * POST /api/auth/profile/switch  { user_id, pin }
 * On success sets the kid's session cookies (2 h refresh), the ftm_sw UX
 * marker, the rotated ftm_home and a renewed ftm_shared hint. Backend
 * 403/429/401 pass through.
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const home = cookies.get("ftm_home")?.value;
    if (!home) return json(401, { success: false, error: "No shared profile session" });
    let user_id: unknown;
    let pin: unknown;
    try {
        ({ user_id, pin } = await request.json());
    } catch {
        return json(400, { success: false, error: "Invalid request" });
    }
    if (typeof user_id !== "string" || typeof pin !== "string") {
        return json(400, { success: false, error: "Invalid request" });
    }
    try {
        const resp = await callProfile(request, home, "switch", "POST", { user_id, pin });
        if (!resp.ok) return errorFrom(resp, "Invalid profile or PIN");
        const d = await resp.json();
        const secure = !import.meta.env.DEV;
        const setCookies = [
            ...authCookies(d.access_token, d.refresh_token, secure, true),
            switchedMarker(secure),
            sharedHintCookie(secure),
            ...uiRoleCookie(d.user?.role, secure),
        ];
        if (d.home_token) setCookies.push(homeCookie(d.home_token, secure));
        return json(200, { success: true }, setCookies);
    } catch {
        return json(500, { success: false, error: "An error occurred connecting to the server" });
    }
};
