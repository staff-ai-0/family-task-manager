import type { APIRoute } from "astro";
import { clearAuthCookies } from "../../../lib/auth-cookies";

/**
 * Proxy for /api/families/me.
 * GET    → backend GET /api/families/me
 * PATCH  → backend PATCH /api/families/me  (parent only; updates name/timezone)
 * DELETE → backend DELETE /api/families/me (parent only; permanent family
 *          deletion with re-auth body). On success the auth cookies are
 *          cleared — every account in the family no longer exists.
 */
const apiUrl = () =>
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
        const r = await fetch(`${apiUrl()}/api/families/me`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        return new Response(await r.text(), {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("families/me GET proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};

export const PATCH: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    let body: any;
    try {
        body = await request.json();
    } catch {
        return new Response(JSON.stringify({ detail: "Invalid JSON" }), {
            status: 400,
            headers: { "Content-Type": "application/json" },
        });
    }
    try {
        const r = await fetch(`${apiUrl()}/api/families/me`, {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify(body),
        });
        return new Response(await r.text(), {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("families/me PATCH proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};

export const DELETE: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    let body: any;
    try {
        body = await request.json();
    } catch {
        return new Response(JSON.stringify({ detail: "Invalid JSON" }), {
            status: 400,
            headers: { "Content-Type": "application/json" },
        });
    }
    try {
        const r = await fetch(`${apiUrl()}/api/families/me`, {
            method: "DELETE",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify(body),
        });
        if (r.status === 204) {
            // The family (and this user) no longer exist — kill the session.
            const headers = new Headers();
            for (const c of clearAuthCookies()) headers.append("Set-Cookie", c);
            headers.append("Set-Cookie", "ui_role=; Path=/; SameSite=Lax; Max-Age=0");
            headers.append("Set-Cookie", "ui_role=; Path=/; SameSite=Lax; Max-Age=0; Secure");
            return new Response(null, { status: 204, headers });
        }
        return new Response(await r.text(), {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("families/me DELETE proxy error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
        });
    }
};
