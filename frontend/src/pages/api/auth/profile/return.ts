import type { APIRoute } from "astro";
import { authCookies, clearSwitchedMarker, uiRoleCookie } from "../../../../lib/auth-cookies";
import { callProfile, errorFrom, json } from "../../../../lib/server/profile-proxy";

/**
 * POST /api/auth/profile/return  { password }
 * The parent's password turns a kid session back into the parent's ordinary
 * session. ftm_home is left untouched (the device stays shared).
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const home = cookies.get("ftm_home")?.value;
    if (!home) return json(401, { success: false, error: "No shared profile session" });
    let password: unknown;
    try {
        ({ password } = await request.json());
    } catch {
        return json(400, { success: false, error: "Invalid request" });
    }
    if (typeof password !== "string" || !password) {
        return json(400, { success: false, error: "Password is required" });
    }
    try {
        const resp = await callProfile(request, home, "return", "POST", { password });
        if (!resp.ok) return errorFrom(resp, "Invalid password");
        const d = await resp.json();
        const setCookies = [
            ...authCookies(d.access_token, d.refresh_token, !import.meta.env.DEV),
            ...clearSwitchedMarker(),
            ...uiRoleCookie(d.user?.role, !import.meta.env.DEV),
        ];
        return json(200, { success: true }, setCookies);
    } catch {
        return json(500, { success: false, error: "An error occurred connecting to the server" });
    }
};
