import type { APIRoute } from "astro";

/**
 * PUT /api/users/{user_id}/role
 * Updates a user's role (parent only)
 */
export const PUT: APIRoute = async ({ request, locals, params }) => {
    try {
        // Check authentication
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

        const body = await request.json();
        const { role } = body;

        if (!role) {
            return new Response(
                JSON.stringify({ success: false, error: "role is required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        const apiUrl = process.env.API_BASE_URL || "http://localhost:8002";
        const response = await fetch(`${apiUrl}/api/users/${user_id}/role?role=${encodeURIComponent(role)}`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`,
            },
        });

        const data = await response.json();

        if (response.ok) {
            return new Response(
                JSON.stringify({ success: true, data }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            );
        }

        const errorMessage = data.detail || "Failed to update role";
        return new Response(
            JSON.stringify({ success: false, error: errorMessage }),
            { status: response.status, headers: { "Content-Type": "application/json" } }
        );
    } catch (e) {
        console.error("Update user role error:", e);
        return new Response(
            JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
