import type { APIRoute } from "astro";

/**
 * DELETE /api/invitations/:familyId/:invitationId
 * Cancels a pending family invitation
 * Requires authentication (parent only)
 */
export const DELETE: APIRoute = async ({ request, params, locals }) => {
    try {
        // Check authentication
        const token = locals.token;
        if (!token) {
            return new Response(
                JSON.stringify({ detail: "Unauthorized" }),
                { status: 401, headers: { "Content-Type": "application/json" } }
            );
        }

        // Extract family_id and invitation_id from URL
        const url = new URL(request.url);
        const pathParts = url.pathname.split('/').filter(p => p);
        // Expected path: api/invitations/familyId/invitationId
        const familyId = pathParts[2];
        const invitationId = pathParts[3];

        if (!familyId || !invitationId) {
            return new Response(
                JSON.stringify({ success: false, error: "family_id and invitation_id are required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        const apiUrl = process.env.API_BASE_URL || "http://localhost:8002";
        const response = await fetch(
            `${apiUrl}/api/invitations/${familyId}/invitations/${invitationId}`,
            {
                method: "DELETE",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`,
                },
            }
        );

        if (response.ok || response.status === 204) {
            return new Response(
                JSON.stringify({ success: true }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            );
        }

        const data = await response.json();
        const errorMessage = data.detail || "Failed to cancel invitation";
        return new Response(
            JSON.stringify({ success: false, error: errorMessage }),
            { status: response.status, headers: { "Content-Type": "application/json" } }
        );
    } catch (e) {
        console.error("Cancel invitation error:", e);
        return new Response(
            JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
