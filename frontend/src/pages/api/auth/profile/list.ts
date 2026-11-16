import type { APIRoute } from "astro";
import { homeCookie, sharedHintCookie } from "../../../../lib/auth-cookies";
import { callProfile, errorFrom, json } from "../../../../lib/server/profile-proxy";

/**
 * GET /api/auth/profile/list
 * Proxies the backend profile list using the ftm_home token, rotates the
 * ftm_home cookie and renews the ftm_shared hint. The token itself is never
 * returned to the browser body.
 */
export const GET: APIRoute = async ({ request, cookies }) => {
    const home = cookies.get("ftm_home")?.value;
    if (!home) return json(401, { success: false, error: "No shared profile session" });
    try {
        const resp = await callProfile(request, home, "list", "GET");
        if (!resp.ok) return errorFrom(resp, "Could not load profiles");
        const data = await resp.json();
        const secure = !import.meta.env.DEV;
        const setCookies = [sharedHintCookie(secure)];
        if (data.home_token) setCookies.push(homeCookie(data.home_token, secure));
        return json(200, { success: true, profiles: data.profiles ?? [] }, setCookies);
    } catch {
        return json(500, { success: false, error: "An error occurred connecting to the server" });
    }
};
