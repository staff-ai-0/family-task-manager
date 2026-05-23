import type { APIRoute } from "astro";

/**
 * GET /api/assignments/pending-approvals
 * Returns the parent-only queue of gigs awaiting approval.
 * Proxies to backend with the caller's access_token cookie as Bearer auth.
 */
export const GET: APIRoute = async ({ cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response("[]", {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }
    const apiUrl =
        process.env.API_BASE_URL ||
        process.env.PUBLIC_API_BASE_URL ||
        "http://backend:8000";

    try {
        const r = await fetch(`${apiUrl}/api/task-assignments/pending-approvals`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        const body = await r.text();
        return new Response(body, {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("pending-approvals proxy error:", e);
        return new Response("[]", {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
