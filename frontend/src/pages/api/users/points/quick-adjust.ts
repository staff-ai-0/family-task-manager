import type { APIRoute } from "astro";

/**
 * POST /api/users/points/quick-adjust
 * Body: { user_id: string, points: number, reason?: string | null }
 * Forwards to backend POST /api/users/points/quick-adjust (parent only).
 *
 * 1-tap points (P1-W4.5): the browser only holds the httpOnly access_token
 * cookie, so this route injects it as the Bearer header the backend expects.
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }

    let body: any;
    try {
        body = await request.json();
    } catch {
        return new Response(JSON.stringify({ detail: "Invalid JSON" }), {
            status: 400,
            headers: { "Content-Type": "application/json" },
        });
    }

    if (!body?.user_id || typeof body.user_id !== "string" || typeof body?.points !== "number") {
        return new Response(JSON.stringify({ detail: "user_id and points required" }), {
            status: 400,
            headers: { "Content-Type": "application/json" },
        });
    }

    const apiUrl =
        process.env.API_BASE_URL ||
        process.env.PUBLIC_API_BASE_URL ||
        "http://backend:8000";

    try {
        const r = await fetch(`${apiUrl}/api/users/points/quick-adjust`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
                user_id: body.user_id,
                points: body.points,
                reason: body.reason ?? null,
            }),
        });
        const text = await r.text();
        return new Response(text, {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("quick-adjust proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
