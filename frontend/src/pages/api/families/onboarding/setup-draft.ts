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

/** UX-E3: the wizard's answers → a draft. POST only; nothing is stored upstream. */
export const POST: APIRoute = async ({ cookies, request }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    try {
        const body = await request.text();
        const r = await fetch(`${API()}/api/families/onboarding/setup-draft`, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
            },
            body,
        });
        return new Response(await r.text(), {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("onboarding/setup-draft POST error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
