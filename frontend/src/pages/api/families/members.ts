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

/** Parent adds a member to their own family (UX-E3 setup wizard). Forwards
 *  the parent's bearer to the backend's parent-only register route — NOT the
 *  public signup proxy at /api/auth/register, which creates a family and
 *  would set the new user's cookies on the parent's browser. The backend
 *  overrides family_id with the caller's; no cookies are touched here. */
export const POST: APIRoute = async ({ cookies, request }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    try {
        const body = await request.text();
        const r = await fetch(`${API()}/api/auth/register`, {
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
        console.error("families/members POST error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
