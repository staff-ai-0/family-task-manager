import type { APIRoute } from "astro";

const API = () =>
    process.env.API_BASE_URL ||
    process.env.PUBLIC_API_BASE_URL ||
    "http://backend:8000";

function unauthorized() {
    return new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
    });
}

export const GET: APIRoute = async ({ cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    try {
        const r = await fetch(`${API()}/api/families/onboarding`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        return new Response(await r.text(), {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("families/onboarding GET error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502, headers: { "Content-Type": "application/json" },
        });
    }
};

export const POST: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    const url = new URL(request.url);
    const backendPath = url.pathname.replace("/api", "");
    try {
        const r = await fetch(`${API()}${backendPath}`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
        });
        return new Response(null, { status: r.status });
    } catch (e) {
        console.error("families/onboarding POST error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502, headers: { "Content-Type": "application/json" },
        });
    }
};
