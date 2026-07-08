import type { APIRoute } from "astro";
import { clientIpHeaders } from "../../../lib/client-ip";

/**
 * Proxy for GET /api/families/export (parent only).
 * Pipes the whole-family export ZIP from the backend, forcing cookie-bearer
 * auth like the other proxies. Binary passthrough — no buffering into text.
 */
const apiUrl = () =>
    process.env.API_BASE_URL ||
    process.env.PUBLIC_API_BASE_URL ||
    "http://backend:8000";

export const GET: APIRoute = async ({ cookies, request }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }
    try {
        const r = await fetch(`${apiUrl()}/api/families/export`, {
            headers: { Authorization: `Bearer ${token}`, ...clientIpHeaders(request) },
        });
        if (!r.ok) {
            return new Response(await r.text(), {
                status: r.status,
                headers: { "Content-Type": "application/json" },
            });
        }
        return new Response(r.body, {
            status: 200,
            headers: {
                "Content-Type": "application/zip",
                "Content-Disposition":
                    r.headers.get("content-disposition") ??
                    'attachment; filename="family-export.zip"',
                "Cache-Control": "no-store",
            },
        });
    } catch (e) {
        console.error("families/export GET proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
