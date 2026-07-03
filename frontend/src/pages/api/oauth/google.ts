import type { APIRoute } from "astro";
import type { LoginResponse, ApiError } from "../../../types/api";
import { authCookies } from "../../../lib/auth-cookies";

/**
 * POST /api/oauth/google
 * Proxies Google OAuth token to backend and sets httpOnly access_token cookie
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    try {
        const body = await request.json();
        const { token, family_id, join_code, role } = body;

        if (!token) {
            return new Response(
                JSON.stringify({ detail: "Google token is required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        // Use internal backend URL for server-side requests
        const apiUrl = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";
        console.log(`[OAuth Google] Using API URL: ${apiUrl}`);
        const response = await fetch(`${apiUrl}/api/oauth/google`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token, family_id, join_code, role }),
        });

        const data = await response.json();

        if (response.ok) {
            const result = data as LoginResponse;

            // Manually set cookies via Set-Cookie header for reliability.
            // NB: named authCks, not `cookies` — the Astro `cookies` API is
            // destructured above and used below (cookies.has("lang")).
            const authCks = authCookies(result.access_token, result.refresh_token, !import.meta.env.DEV);

            const headers = new Headers({ "Content-Type": "application/json" });
            for (const c of authCks) headers.append("Set-Cookie", c);

            // Mirror login.ts: sync UI language + role cookies from the account
            // so a Spanish-speaking family isn't dumped into English (and kid
            // pages into adult mode) after every Google sign-in on a new device.
            const secure = import.meta.env.DEV ? "" : "; Secure";
            // Restore the account language only when this browser has no lang
            // cookie yet (new device / cleared storage). A brand-new Google
            // account defaults to "en" server-side and must not clobber the
            // Spanish the user was already browsing in.
            const pl = String((result.user as any)?.preferred_lang || "").toLowerCase();
            if (!cookies.has("lang") && (pl === "en" || pl === "es")) {
                headers.append("Set-Cookie", `lang=${pl}; Path=/; Max-Age=${60 * 60 * 24 * 365}; SameSite=Lax${secure}`);
            }
            const uiRole = String((result.user as any)?.role || "").toLowerCase();
            if (uiRole) {
                headers.append("Set-Cookie", `ui_role=${uiRole}; Path=/; Max-Age=${60 * 60 * 24 * 7}; SameSite=Lax${secure}`);
            }

            return new Response(
                JSON.stringify({ success: true, user: result.user }),
                { status: 200, headers }
            );
        } else {
            return new Response(
                JSON.stringify(data),
                { status: response.status, headers: { "Content-Type": "application/json" } }
            );
        }
    } catch (e) {
        console.error("Google OAuth proxy error:", e);
        return new Response(
            JSON.stringify({ detail: "An error occurred during Google authentication" }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
