import type { APIRoute } from "astro";

/**
 * POST /api/subscriptions/checkout
 *
 * Forwards to backend subscription checkout endpoint, attaching the user's
 * access_token (httpOnly cookie) as an Authorization header. Backend returns
 * { approval_url, ... } that the client redirects to (PayPal).
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }

    const body = await request.text();
    const backend = process.env.API_BASE_URL || process.env.PUBLIC_API_BASE_URL || "http://localhost:8002";
    const resp = await fetch(`${backend}/api/subscriptions/checkout`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
        },
        body,
    });
    const text = await resp.text();
    return new Response(text, {
        status: resp.status,
        headers: { "Content-Type": "application/json" },
    });
};
