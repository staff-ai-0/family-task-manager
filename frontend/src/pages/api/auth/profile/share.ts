import type { APIRoute } from "astro";
import { homeCookie } from "../../../../lib/auth-cookies";
import { json } from "../../../../lib/server/profile-proxy";

/**
 * POST /api/auth/profile/share
 * A signed-in parent marks this device as shared: their ordinary refresh
 * cookie is copied into the narrowly-scoped ftm_home cookie. No backend call;
 * the backend re-validates the token on every profile/* use.
 */
export const POST: APIRoute = async ({ cookies }) => {
    const refresh = cookies.get("refresh_token")?.value;
    if (!refresh) return json(401, { success: false, error: "Not signed in" });
    return json(200, { success: true }, [homeCookie(refresh, !import.meta.env.DEV)]);
};
