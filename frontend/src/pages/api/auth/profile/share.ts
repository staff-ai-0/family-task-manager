import type { APIRoute } from "astro";
import { clearAuthCookies, clearSwitchedMarker, homeCookie } from "../../../../lib/auth-cookies";
import { json } from "../../../../lib/server/profile-proxy";

/**
 * POST /api/auth/profile/share
 * A signed-in parent marks this device as shared: their ordinary refresh
 * cookie is copied into the narrowly-scoped ftm_home cookie (no backend call;
 * the backend re-validates it on every use), and the ordinary session is
 * cleared so the device rests at the picker. The parent returns via
 * profile/return (password).
 */
export const POST: APIRoute = async ({ cookies }) => {
    const refresh = cookies.get("refresh_token")?.value;
    if (!refresh) return json(401, { success: false, error: "Not signed in" });
    const setCookies = [
        homeCookie(refresh, !import.meta.env.DEV),
        ...clearAuthCookies(),
        ...clearSwitchedMarker(),
        "ui_role=; Path=/; SameSite=Lax; Max-Age=0",
        "ui_role=; Path=/; SameSite=Lax; Max-Age=0; Secure",
    ];
    return json(200, { success: true }, setCookies);
};
