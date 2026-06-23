import type { APIRoute } from "astro";

/**
 * POST /api/onboarding/events — forwards a welcome-tour funnel event to the
 * backend. Called via navigator.sendBeacon (which can't set an Authorization
 * header but does send cookies), so we read the access_token cookie and attach
 * the Bearer token, then pipe the JSON body through.
 */
export const POST: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return new Response(null, { status: 401 });

    const apiUrl =
        process.env.API_BASE_URL ||
        process.env.PUBLIC_API_BASE_URL ||
        "http://backend:8000";

    let body = "{}";
    try {
        body = (await request.text()) || "{}";
    } catch {
        /* keep default */
    }

    try {
        const r = await fetch(`${apiUrl}/api/families/onboarding/events`, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
            },
            body,
        });
        return new Response(null, { status: r.status });
    } catch (e) {
        console.error("onboarding events proxy error:", e);
        return new Response(null, { status: 502 });
    }
};
