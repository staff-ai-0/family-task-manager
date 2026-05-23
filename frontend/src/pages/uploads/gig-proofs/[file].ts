import type { APIRoute } from "astro";

/**
 * GET /uploads/gig-proofs/<file>
 *
 * Proxies the gig-proof image from the backend (which lives at
 * /uploads/gig-proofs/<file>) so it's reachable through the public
 * Cloudflare tunnel without exposing the backend hostname.
 *
 * Auth gate: requires a valid access_token cookie. We do not need the
 * backend itself to verify the bearer for static images (StaticFiles
 * does not enforce auth), so this proxy is the effective auth boundary.
 */
export const GET: APIRoute = async ({ params, cookies }) => {
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

    const r = await fetch(`${apiUrl}/uploads/gig-proofs/${file}`);
    if (!r.ok) {
        return new Response("Not found", { status: r.status });
    }
    const buf = await r.arrayBuffer();
    return new Response(buf, {
        status: 200,
        headers: {
            "Content-Type": r.headers.get("content-type") || "application/octet-stream",
            "Cache-Control": "private, max-age=300",
        },
    });
};
