import type { APIRoute } from "astro";
import type { LoginResponse, ApiError } from "../../../types/api";

/**
 * POST /api/oauth/google
 * Proxies Google OAuth token to backend and sets httpOnly access_token cookie
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    try {
        const body = await request.json();
        const { token, family_id, join_code } = body;

        if (!token) {
            return new Response(
                JSON.stringify({ detail: "Google token is required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        // Use runtime environment variable (SSR)
        const apiUrl = process.env.PUBLIC_API_URL ?? "http://localhost:8002";
        console.log(`[OAuth Google] Using API URL: ${apiUrl}`);
        const response = await fetch(`${apiUrl}/api/oauth/google`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token, family_id, join_code }),
        });

        const data = await response.json();

        if (response.ok) {
            const result = data as LoginResponse;

            // Set httpOnly secure cookie server-side
            cookies.set("access_token", result.access_token, {
                path: "/",
                httpOnly: true,
                sameSite: "lax",
                maxAge: 60 * 60 * 24 * 7, // 7 days
                secure: import.meta.env.PROD,
            });

            return new Response(
                JSON.stringify({ success: true, user: result.user }),
                { status: 200, headers: { "Content-Type": "application/json" } }
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
