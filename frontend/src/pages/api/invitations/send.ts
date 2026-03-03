import type { APIRoute } from "astro";

/**
 * POST /api/invitations/send
 * Sends a family invitation to an email address
 * Requires authentication (parent only)
 */
export const POST: APIRoute = async ({ request, locals }) => {
    try {
        // Check authentication
        const token = locals.token;
        if (!token) {
            return new Response(
                JSON.stringify({ detail: "Unauthorized" }),
                { status: 401, headers: { "Content-Type": "application/json" } }
            );
        }

        const body = await request.json();
        const { email, message, family_id, role } = body;

        if (!email || !family_id) {
            return new Response(
                JSON.stringify({ success: false, error: "email and family_id are required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        const apiUrl = process.env.API_BASE_URL || "http://localhost:8002";
        const response = await fetch(`${apiUrl}/api/invitations/send`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`,
            },
            body: JSON.stringify({ email, message, family_id, role: role || "child" }),
        });

        const data = await response.json();

        if (response.ok) {
            return new Response(
                JSON.stringify({ success: true, data }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            );
        }

        const errorMessage = data.detail || "Failed to send invitation";
        return new Response(
            JSON.stringify({ success: false, error: errorMessage }),
            { status: response.status, headers: { "Content-Type": "application/json" } }
        );
    } catch (e) {
        console.error("Send invitation error:", e);
        return new Response(
            JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
