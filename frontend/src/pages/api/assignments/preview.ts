import type { APIRoute } from "astro";

/**
 * GET /api/assignments/preview?week_of=YYYY-MM-DD
 * Proxies to backend GET /api/task-assignments/shuffle/preview, attaching the
 * user's access token from the cookie. Returns the preview JSON unchanged.
 */
export const GET: APIRoute = async ({ url, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ detail: "Unauthenticated" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }

    const weekOf = url.searchParams.get("week_of");
    const qs = weekOf ? `?week_of=${encodeURIComponent(weekOf)}` : "";
    const apiUrl = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://backend:8000";

    try {
        const response = await fetch(`${apiUrl}/api/task-assignments/shuffle/preview${qs}`, {
            method: "GET",
            headers: { "Authorization": `Bearer ${token}` },
        });
        const body = await response.text();
        return new Response(body, {
            status: response.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("Preview proxy error:", e);
        return new Response(JSON.stringify({ detail: "Server error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
