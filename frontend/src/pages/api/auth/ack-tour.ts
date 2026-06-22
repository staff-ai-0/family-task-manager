import type { APIRoute } from "astro";

/**
 * POST /api/auth/ack-tour
 * Forwards to backend POST /api/auth/ack-tour to mark the interactive
 * welcome tour as completed/skipped for the current user. Mirrors
 * ack-gigs-intro.ts.
 */
export const POST: APIRoute = async ({ cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }

    const apiUrl =
        process.env.API_BASE_URL ||
        process.env.PUBLIC_API_BASE_URL ||
        "http://backend:8000";

    try {
        const r = await fetch(`${apiUrl}/api/auth/ack-tour`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
        });
        const text = await r.text();
        return new Response(text, {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("ack-tour proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
