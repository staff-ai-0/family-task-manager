import type { APIRoute } from "astro";

/**
 * POST /api/auth/check-methods
 * Proxies to backend to find which auth methods (password, google) are
 * configured for a given email. Used by the login form to redirect
 * OAuth-only users to Google sign-in before asking for a password.
 */
export const POST: APIRoute = async ({ request }) => {
    try {
        const body = await request.json();
        const { email } = body;

        if (!email || typeof email !== "string") {
            return new Response(
                JSON.stringify({ has_password: false, has_google: false }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            );
        }

        const apiUrl =
            process.env.API_BASE_URL ||
            process.env.PUBLIC_API_BASE_URL ||
            "http://localhost:8002";

        const response = await fetch(`${apiUrl}/api/auth/check-methods`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email }),
        });

        // On any non-OK response, fail safe to "no known methods" so the
        // frontend falls through to the normal password flow.
        if (!response.ok) {
            return new Response(
                JSON.stringify({ has_password: false, has_google: false }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            );
        }

        const data = await response.json();
        return new Response(JSON.stringify(data), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("check-methods proxy error:", e);
        return new Response(
            JSON.stringify({ has_password: false, has_google: false }),
            { status: 200, headers: { "Content-Type": "application/json" } }
        );
    }
};
