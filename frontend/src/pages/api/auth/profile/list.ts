import type { APIRoute } from "astro";
import { homeCookie } from "../../../../lib/auth-cookies";
import { callProfile, errorFrom, json } from "../../../../lib/server/profile-proxy";

/**
 * GET /api/auth/profile/list
 * Proxies the backend profile list using the ftm_home token and rotates the
 * ftm_home cookie. The token itself is never returned to the browser body.
 */
export const GET: APIRoute = async ({ request, cookies }) => {
    const home = cookies.get("ftm_home")?.value;
    if (!home) return json(401, { success: false, error: "No shared profile session" });
    try {
        const resp = await callProfile(request, home, "list", "GET");
        if (!resp.ok) return errorFrom(resp, "Could not load profiles");
        const data = await resp.json();
        const setCookies = data.home_refresh_token
            ? [homeCookie(data.home_refresh_token, !import.meta.env.DEV)]
            : [];
        return json(200, { success: true, profiles: data.profiles ?? [] }, setCookies);
    } catch {
        return json(500, { success: false, error: "An error occurred connecting to the server" });
    }
};
