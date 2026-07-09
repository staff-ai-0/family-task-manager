import type { APIRoute } from "astro";

/**
 * GET /uploads/gig-proofs/<file>
 *
 * Proxies the gig-proof image from the backend (which lives at
 * /uploads/gig-proofs/<file>) so it's reachable through the public
 * Cloudflare tunnel without exposing the backend hostname.
 *
 * Auth gate: requires a valid access_token cookie AND forwards it as a bearer
 * token. The backend route is itself authenticated and family-scoped, so the
 * image is never served without both the cookie here and ownership there.
 */
export const GET: APIRoute = async ({ params, cookies, request }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response("Unauthorized", { status: 401 });
    }
    const file = params.file;
    if (!file || /[\\/]/.test(file)) {
        return new Response("Bad request", { status: 400 });
    }

    const apiUrl =
        process.env.API_BASE_URL ||
        process.env.PUBLIC_API_BASE_URL ||
        "http://backend:8000";

    // Forward ?size=thumb (and any other query) so the backend can serve the
    // small WebP thumbnail for list/approval views.
    const search = new URL(request.url).search;

    const r = await fetch(`${apiUrl}/uploads/gig-proofs/${file}${search}`, {
        headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) {
        return new Response("Not found", { status: r.status });
    }
    const buf = await r.arrayBuffer();
    return new Response(buf, {
        status: 200,
        headers: {
            "Content-Type": r.headers.get("content-type") || "application/octet-stream",
            // UUID-named files are immutable — mirror the backend's long cache.
            "Cache-Control":
                r.headers.get("cache-control") ||
                "private, max-age=31536000, immutable",
        },
    });
};
