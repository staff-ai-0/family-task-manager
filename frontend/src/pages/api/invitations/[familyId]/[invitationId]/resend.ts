import type { APIRoute } from "astro";

/**
 * POST /api/invitations/:familyId/:invitationId/resend
 * Re-sends a pending family invitation email (refreshes expiry).
 * Requires authentication (parent only)
 */
export const POST: APIRoute = async ({ request, params, locals }) => {
    try {
        const token = locals.token;
        if (!token) {
            return new Response(
                JSON.stringify({ detail: "Unauthorized" }),
                { status: 401, headers: { "Content-Type": "application/json" } }
            );
        }

        const familyId = params.familyId;
        const invitationId = params.invitationId;

        if (!familyId || !invitationId) {
            return new Response(
                JSON.stringify({ success: false, error: "family_id and invitation_id are required" }),
                { status: 400, headers: { "Content-Type": "application/json" } }
            );
        }

        const apiUrl = process.env.API_BASE_URL || "http://localhost:8002";
        const response = await fetch(
            `${apiUrl}/api/invitations/${familyId}/${invitationId}/resend`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`,
                },
            }
        );

        const data = await response.json().catch(() => ({}));

        if (response.ok) {
            return new Response(
                JSON.stringify({ success: true, data }),
                { status: 200, headers: { "Content-Type": "application/json" } }
            );
        }

        const errorMessage = data.detail || "Failed to resend invitation";
        return new Response(
            JSON.stringify({ success: false, error: errorMessage }),
            { status: response.status, headers: { "Content-Type": "application/json" } }
        );
    } catch (e) {
        console.error("Resend invitation error:", e);
        return new Response(
            JSON.stringify({ success: false, error: "An error occurred. Please try again." }),
            { status: 500, headers: { "Content-Type": "application/json" } }
        );
    }
};
