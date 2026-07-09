import type { APIRoute } from "astro";

/**
 * PUT /api/users/{user_id}/star-mode
 * Toggle a kid's Star Mode young-kid display (parent only). Forwards the JSON
 * body { enabled: boolean } to the backend with the caller's bearer token.
 */
export const PUT: APIRoute = async ({ request, locals, params }) => {
    try {
        const token = locals.token;
        if (!token) {
            return new Response(
                JSON.stringify({ detail: "Unauthorized" }),
                { status: 401, headers: { "Content-Type": "application/json" } }
            );
        }

        const { user_id } = params;
        if (!user_id) {
            return new Response(
                JSON.stringify({ success: false, error: "user_id is required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        const body = await request.json().catch(() => ({}));
        const enabled = Boolean(body?.enabled);

        const apiUrl = process.env.API_BASE_URL || "http://localhost:8002";
        const response = await fetch(`${apiUrl}/api/users/${user_id}/star-mode`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({ enabled }),
        });

        const data = await response.json().catch(() => ({}));

        if (response.ok) {
            return new Response(
                JSON.stringify({ success: true, data }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            );
        }

        const errorMessage = data.detail || "Failed to update star mode";
        return new Response(
            JSON.stringify({ success: false, error: errorMessage }),
            { status: response.status, headers: { "Content-Type": "application/json" } }
        );
    } catch (e) {
        console.error("Update star mode error:", e);
        return new Response(
            JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
