import type { APIRoute } from "astro";

const apiUrl = () =>
    process.env.API_BASE_URL ||
    process.env.PUBLIC_API_BASE_URL ||
    "http://backend:8000";

export const GET: APIRoute = async ({ cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) {
        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
        });
    }
    try {
        const r = await fetch(`${apiUrl()}/api/push/public-key`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        return new Response(await r.text(), {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("push/public-key proxy:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
