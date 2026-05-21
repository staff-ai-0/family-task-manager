import type { APIRoute } from "astro";

/**
 * POST /api/subscriptions/cancel
 *
 * Forwards to backend cancel endpoint, attaching the user's access_token
 * (httpOnly cookie) as an Authorization header. Backend marks the
 * FamilySubscription cancel_at_period_end=true (cancel-at-period-end
 * semantics) and cancels at PayPal.
 */
export const POST: APIRoute = async ({ cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }

    const backend = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";
    const resp = await fetch(`${backend}/api/subscriptions/cancel`, {
        method: "POST",
        headers: {
            Authorization: `Bearer ${token}`,
        },
    });
    const text = await resp.text();
    return new Response(text, {
        status: resp.status,
        headers: { "Content-Type": "application/json" },
    });
};
