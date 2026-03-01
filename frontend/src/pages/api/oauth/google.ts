import type { APIRoute } from "astro";
import type { LoginResponse, ApiError } from "../../../types/api";

/**
 * Helper to build a Set-Cookie header string.
 */
function buildCookie(name: string, value: string, options: {
    path?: string;
    httpOnly?: boolean;
    sameSite?: string;
    maxAge?: number;
    secure?: boolean;
}): string {
    let cookie = `${name}=${encodeURIComponent(value)}`;
    if (options.path) cookie += `; Path=${options.path}`;
    if (options.httpOnly) cookie += "; HttpOnly";
    if (options.secure) cookie += "; Secure";
    if (options.sameSite) cookie += `; SameSite=${options.sameSite}`;
    if (options.maxAge !== undefined) cookie += `; Max-Age=${options.maxAge}`;
    return cookie;
}

/**
 * POST /api/oauth/google
 * Proxies Google OAuth token to backend and sets httpOnly access_token cookie
 */
export const POST: APIRoute = async ({ request }) => {
    try {
        const body = await request.json();
        const { token, family_id, join_code } = body;

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
            body: JSON.stringify({ token, family_id, join_code }),
        });

        const data = await response.json();

        if (response.ok) {
            const result = data as LoginResponse;

            // Manually set cookie via Set-Cookie header for reliability
            const tokenCookie = buildCookie("access_token", result.access_token, {
                path: "/",
                httpOnly: true,
                sameSite: "Lax",
                maxAge: 60 * 60 * 24 * 7, // 7 days
                secure: import.meta.env.PROD,
            });

            const headers = new Headers({ "Content-Type": "application/json" });
            headers.append("Set-Cookie", tokenCookie);

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
