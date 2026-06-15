import type { APIRoute } from "astro";
import { clearAuthCookies } from "../../../lib/auth-cookies";

/**
 * POST /api/auth/logout
 * Best-effort revokes the session server-side (bumps token_version,
 * logging out everywhere), then clears both auth cookies + ui_role.
 */
export const POST: APIRoute = async ({ cookies }) => {
    // Bump token_version server-side (logout-everywhere) before clearing cookies.
    const access = cookies.get("access_token")?.value;
    if (access) {
        const api = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";
        try {
            await fetch(`${api}/api/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${access}` } });
        } catch { /* best-effort; still clear cookies below */ }
    }
    const headers = new Headers({ Location: "/login" });
    for (const c of clearAuthCookies()) headers.append("Set-Cookie", c);
    headers.append("Set-Cookie", "ui_role=; Path=/; SameSite=Lax; Max-Age=0");
    headers.append("Set-Cookie", "ui_role=; Path=/; SameSite=Lax; Max-Age=0; Secure");
    return new Response(null, { status: 302, headers });
};
