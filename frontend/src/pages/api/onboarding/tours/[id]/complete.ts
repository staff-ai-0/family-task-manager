import type { APIRoute } from "astro";

/**
 * POST /api/onboarding/tours/:id/complete
 *
 * Marks a per-module tour finished or skipped for the current user. Mirrors
 * api/auth/ack-tour.ts, which does the same for the welcome tour's boolean.
 *
 * Called by navigator.sendBeacon, which sends no body and cannot read the
 * response — so this must stay a plain POST and must not require one.
 */
export const POST: APIRoute = async ({ params, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }

    const id = params.id ?? "";
    // The backend allowlists the id too (TOUR_IDS); this only keeps a junk
    // path segment from being pasted into the upstream URL.
    if (!/^[a-z-]{1,40}$/.test(id)) {
        return new Response(JSON.stringify({ detail: "Unknown tour id" }), {
            status: 422,
            headers: { "Content-Type": "application/json" },
        });
    }

    const apiUrl =
        process.env.API_BASE_URL ||
        process.env.PUBLIC_API_BASE_URL ||
        "http://backend:8000";

    try {
        const r = await fetch(
            `${apiUrl}/api/families/onboarding/tours/${id}/complete`,
            { method: "POST", headers: { Authorization: `Bearer ${token}` } },
        );
        return new Response(r.status === 204 ? null : await r.text(), {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("tour-complete proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
