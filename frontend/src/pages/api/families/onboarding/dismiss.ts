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

export const POST: APIRoute = async ({ cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    try {
        const r = await fetch(`${API()}/api/families/onboarding/dismiss`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
        });
        return new Response(null, { status: r.status });
    } catch (e) {
        console.error("families/onboarding/dismiss POST error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
