import type { APIRoute } from "astro";

/**
 * POST /api/auth/ack-gigs-intro
 * Forwards to backend POST /api/auth/ack-gigs-intro to dismiss the
 * mandatory=0 / gigs=points scope-change banner.
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
        const r = await fetch(`${apiUrl}/api/auth/ack-gigs-intro`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
        });
        const text = await r.text();
        return new Response(text, {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("ack-gigs-intro proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
