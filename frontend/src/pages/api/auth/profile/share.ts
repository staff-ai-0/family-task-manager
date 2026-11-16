import type { APIRoute } from "astro";
import {
    clearAuthCookies,
    clearSwitchedMarker,
    homeCookie,
    sharedHintCookie,
} from "../../../../lib/auth-cookies";
import { callProfile, errorFrom, json } from "../../../../lib/server/profile-proxy";

/**
 * POST /api/auth/profile/share
 * A signed-in parent marks this device as shared. The parent's ACCESS token
 * goes to backend profile/share, which returns a "home" token (its own JWT
 * type, refused by /api/auth/refresh); that token becomes the narrowly-scoped
 * ftm_home cookie. The parent's refresh token is never copied: it would be a
 * 30-day parent session for whoever copies the cookie out of DevTools.
 * The ordinary session is then cleared so the device rests at the picker, and
 * ftm_shared marks the device as shared. The parent returns via
 * profile/return (password).
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const access = cookies.get("access_token")?.value;
    if (!access) return json(401, { success: false, error: "Not signed in" });
    try {
        const resp = await callProfile(request, access, "share", "POST");
        if (!resp.ok) return errorFrom(resp, "Could not share this device");
        const d = await resp.json();
        if (typeof d?.home_token !== "string" || !d.home_token) {
            return json(500, { success: false, error: "Could not share this device" });
        }
        const secure = !import.meta.env.DEV;
        const setCookies = [
            homeCookie(d.home_token, secure),
            sharedHintCookie(secure),
            ...clearAuthCookies(),
            ...clearSwitchedMarker(),
            "ui_role=; Path=/; SameSite=Lax; Max-Age=0",
            "ui_role=; Path=/; SameSite=Lax; Max-Age=0; Secure",
        ];
        return json(200, { success: true }, setCookies);
    } catch {
        return json(500, { success: false, error: "An error occurred connecting to the server" });
    }
};
