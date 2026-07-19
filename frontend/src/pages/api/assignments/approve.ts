import type { APIRoute } from "astro";

/**
 * POST /api/assignments/approve
 * Body: { assignment_id: string, approve: boolean, notes?: string | null }
 * Forwards to backend POST /api/task-assignments/{id}/approve
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

    const assignmentId = body?.assignment_id;
    if (!assignmentId || typeof assignmentId !== "string") {
        return new Response(JSON.stringify({ detail: "assignment_id required" }), {
            status: 400,
            headers: { "Content-Type": "application/json" },
        });
    }

    const apiUrl =
        process.env.API_BASE_URL ||
        process.env.PUBLIC_API_BASE_URL ||
        "http://backend:8000";

    try {
        const r = await fetch(
            `${apiUrl}/api/task-assignments/${assignmentId}/approve`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                    approve: Boolean(body.approve),
                    notes: body.notes ?? null,
                    grade: body.grade ?? null,
                    partial_credit_pct: body.partial_credit_pct ?? null,
                }),
            }
        );
        const text = await r.text();
        return new Response(text, {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("approve proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
