import type { APIRoute } from "astro";

/**
 * GET /api/invitations/pending?family_id=...
 * Gets pending family invitations for a specific family
 * Requires authentication (parent only)
 */
export const GET: APIRoute = async ({ request, url, locals }) => {
    try {
        // Check authentication
        const token = locals.token;
        if (!token) {
            return new Response(
                JSON.stringify({ detail: "Unauthorized" }),
                { status: 401, headers: { "Content-Type": "application/json" } }
            );
        }

        const familyId = url.searchParams.get("family_id");
        if (!familyId) {
            return new Response(
                JSON.stringify({ success: false, error: "family_id query parameter is required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        const apiUrl = process.env.API_BASE_URL || "http://localhost:8002";
        const response = await fetch(
            `${apiUrl}/api/invitations/${familyId}/pending`,
            {
                method: "GET",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`,
                },
            }
        );

        const data = await response.json();

        if (response.ok) {
            return new Response(
                JSON.stringify({ success: true, data }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            );
        }

        const errorMessage = data.detail || "Failed to fetch pending invitations";
        return new Response(
            JSON.stringify({ success: false, error: errorMessage }),
            { status: response.status, headers: { "Content-Type": "application/json" } }
        );
    } catch (e) {
        console.error("Get pending invitations error:", e);
        return new Response(
            JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
